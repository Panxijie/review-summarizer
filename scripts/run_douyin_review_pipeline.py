#!/usr/bin/env python3
"""Run a detached, self-supervising Douyin summary and review-append pipeline."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SUMMARY = SKILL_DIR / "scripts/summarize_notes_with_model.py"
ORGANIZER = SKILL_DIR / "scripts/organize_content_library.py"
BACKFILL = SKILL_DIR / "scripts/backfill_douyin_local_file_links.py"
ALLOWED_CATEGORIES = {
    "技术与工具", "科研与学习", "财务与资产", "职场与发展",
    "情感与关系", "日常与生活", "待分类",
}
ACTIVE_CHILD: subprocess.Popen | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path, help=".../raw/originals/douyin")
    parser.add_argument("--pull-id", required=True)
    parser.add_argument("--pulled-at", help="Pull start time in YYYY-MM-DD HH:MM; inferred from pull-id when omitted.")
    parser.add_argument("--detach", action="store_true", help="Start one detached supervisor process and return its PID.")
    return parser.parse_args()


def paths(args: argparse.Namespace) -> dict[str, Path | str]:
    output = args.output_root.resolve()
    vault_root = output.parents[2]
    pull_id = args.pull_id
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2}).*", pull_id)
    pulled_at = args.pulled_at or (f"{match.group(1)} {match.group(2)}:{match.group(3)}" if match else None)
    if not pulled_at:
        raise SystemExit("--pulled-at is required when pull-id does not begin YYYY-MM-DD_HH-mm")
    datetime_match = re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", pulled_at)
    if not datetime_match:
        raise SystemExit("--pulled-at must use YYYY-MM-DD HH:MM")
    manifest = args.manifest.resolve()
    if not manifest.is_file():
        raise SystemExit(f"Manifest not found: {manifest}")
    if output.name != "douyin":
        raise SystemExit("--output-root must end in raw/originals/douyin")
    review = output.parents[1] / "review/current"
    json_dir = manifest.parent
    return {
        "output": output,
        "vault_root": vault_root,
        "pull_id": pull_id,
        "pulled_at": pulled_at,
        "manifest": manifest,
        "review": review,
        "json_dir": json_dir,
        "log": json_dir / "review-supervisor.log",
        "summary_log": json_dir / "summary-retry.log",
        "lock": json_dir / ".review-pipeline.lock",
        "pid": json_dir / "review-supervisor.pid",
    }


def spawn_detached(args: argparse.Namespace, p: dict[str, Path | str]) -> int:
    command = [
        sys.executable, str(Path(__file__).resolve()),
        "--manifest", str(p["manifest"]), "--output-root", str(p["output"]),
        "--pull-id", str(p["pull_id"]), "--pulled-at", str(p["pulled_at"]),
    ]
    log_path = Path(p["log"])
    with log_path.open("a", encoding="utf-8") as log_stream:
        child = subprocess.Popen(
            command, cwd=str(p["vault_root"]), stdin=subprocess.DEVNULL,
            stdout=log_stream, stderr=subprocess.STDOUT, start_new_session=True,
            close_fds=True,
        )
    Path(p["pid"]).write_text(f"{child.pid}\n", encoding="utf-8")
    print(f"supervisor_started pid={child.pid} log={log_path}")
    return 0


def log(p: dict[str, Path | str], message: str) -> None:
    with Path(p["log"]).open("a", encoding="utf-8") as stream:
        stream.write(time.strftime("%Y-%m-%d %H:%M:%S ") + message + "\n")


def handle_signal(signum: int, _frame: object) -> None:
    if ACTIVE_CHILD and ACTIVE_CHILD.poll() is None:
        ACTIVE_CHILD.terminate()
        try:
            ACTIVE_CHILD.wait(timeout=10)
        except subprocess.TimeoutExpired:
            ACTIVE_CHILD.kill()
    raise SystemExit(128 + signum)


def current_review_index(review_root: Path) -> dict[tuple[str, int], dict]:
    notes: dict[tuple[str, int], dict] = {}
    for note in review_root.rglob("*.md"):
        if note.name == "README.md":
            continue
        try:
            text = note.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        frontmatter = re.match(r"(?s)^---\s*\n(.*?)\n---(?:\s*\n|$)", text)
        if not frontmatter:
            continue
        metadata = frontmatter.group(1)
        pull = re.search(r"(?m)^pull_id:\s*['\"]?([^\s'\"]+)['\"]?\s*$", metadata)
        index = re.search(r"(?m)^manifest_item_index:\s*(\d+)\s*$", metadata)
        aweme = re.search(r"(?m)^aweme_id:\s*['\"]?([0-9]{16,20})['\"]?\s*$", metadata)
        if pull and index:
            notes[(pull.group(1), int(index.group(1)))] = {
                "path": note,
                "aweme_id": aweme.group(1) if aweme else None,
            }
    return notes


def current_review_aweme_ids(review_root: Path) -> set[str]:
    ids: set[str] = set()
    for note in review_root.rglob("*.md"):
        if note.name == "README.md":
            continue
        try:
            text = note.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        frontmatter = re.match(r"(?s)^---\s*\n(.*?)\n---(?:\s*\n|$)", text)
        if frontmatter:
            match = re.search(r"(?m)^aweme_id:\s*['\"]?([0-9]{16,20})['\"]?\s*$", frontmatter.group(1))
            if match:
                ids.add(match.group(1))
    return ids


def reconcile_current_notes(p: dict[str, Path | str], notes: dict[tuple[str, int], dict]) -> None:
    manifest_path = Path(p["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    changed = False
    for item in manifest:
        key = (str(p["pull_id"]), int(item.get("index", 0)))
        existing = notes.get(key)
        if not existing or (existing.get("aweme_id") and str(item.get("aweme_id")) != existing["aweme_id"]):
            continue
        current_value = item.get("note")
        current_path = resolve_local(current_value, p) if current_value else None
        if not current_path or not current_path.is_file():
            item["note"] = str(existing["path"].resolve().relative_to(Path(p["vault_root"]).resolve()))
            changed = True
    if changed:
        temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(manifest_path)


def selected_items(p: dict[str, Path | str]) -> tuple[list[dict], list[dict]]:
    manifest = json.loads(Path(p["manifest"]).read_text(encoding="utf-8"))
    review_index = current_review_index(Path(p["review"]))
    existing_ids = current_review_aweme_ids(Path(p["review"]))
    selected, duplicates = [], []
    for item in manifest:
        if item.get("status") != "ok":
            continue
        own = review_index.get((str(p["pull_id"]), int(item.get("index", 0))))
        own_match = own and own.get("aweme_id") == str(item.get("aweme_id"))
        old_match = not own_match and item.get("aweme_id") and str(item["aweme_id"]) in existing_ids
        (duplicates if item.get("aweme_id") and old_match else selected).append(item)
    return selected, duplicates


def indices_to_organize(p: dict[str, Path | str], selected: list[dict]) -> list[int]:
    review_index = current_review_index(Path(p["review"]))
    result = []
    for item in selected:
        index = int(item.get("index", 0))
        row = review_index.get((str(p["pull_id"]), index))
        if row and row.get("aweme_id") == str(item.get("aweme_id")):
            continue
        result.append(index)
    return sorted(result)


def resolve_local(value: str, p: dict[str, Path | str]) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    candidates = [Path.cwd() / path, Path(p["vault_root"]) / path]
    vault_root = Path(p["vault_root"])
    if path.parts and path.parts[0] == vault_root.name:
        candidates.append(vault_root.parent / path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def completion_errors(p: dict[str, Path | str]) -> tuple[list[dict], list[str]]:
    selected, _ = selected_items(p)
    errors: list[str] = []
    for item in selected:
        idx = int(item.get("index", 0))
        note_value, transcript_value = item.get("note"), item.get("transcript")
        if not note_value or not transcript_value:
            errors.append(f"index_{idx}_missing_note_or_transcript")
            continue
        note, transcript = resolve_local(note_value, p), resolve_local(transcript_value, p)
        if not note.is_file() or not transcript.is_file():
            errors.append(f"index_{idx}_missing_note_or_transcript")
            continue
        text = note.read_text(encoding="utf-8", errors="replace")
        if not item.get("summary_model") or not item.get("summary_generated_at"):
            errors.append(f"index_{idx}_missing_summary_metadata")
        if any(h not in text for h in ("## 摘要", "## 详细内容", "## 注意事项")):
            errors.append(f"index_{idx}_missing_required_heading")
        if "## 内容脉络（自动提取）" in text or "## 整理状态" in text:
            errors.append(f"index_{idx}_fallback_heading")
    if not selected:
        errors.append("no_new_review_candidates")
    return selected, errors


def run_stage(p: dict[str, Path | str], label: str, command: list[str], *, summary: bool = False) -> subprocess.CompletedProcess[str]:
    global ACTIVE_CHILD
    log(p, f"stage_start={label}")
    if summary:
        with Path(p["summary_log"]).open("a", encoding="utf-8") as stream:
            ACTIVE_CHILD = subprocess.Popen(command, cwd=str(p["vault_root"]), stdout=stream, stderr=subprocess.STDOUT, text=True)
            code = ACTIVE_CHILD.wait()
        ACTIVE_CHILD = None
        result = subprocess.CompletedProcess(command, code, "", "")
    else:
        result = subprocess.run(command, cwd=str(p["vault_root"]), capture_output=True, text=True)
    log(p, f"stage_end={label} exit_code={result.returncode}")
    return result


def verify_final(p: dict[str, Path | str]) -> tuple[int, list[str]]:
    selected, errors = completion_errors(p)
    for item in selected:
        idx = int(item.get("index", 0))
        note = resolve_local(item.get("note") or "", p)
        if not note.is_file():
            errors.append(f"index_{idx}_review_note_missing")
            continue
        text = note.read_text(encoding="utf-8", errors="replace")
        headings = [m.start() for m in re.finditer(r"(?m)^## ", text)]
        if "## 本地文件" not in text:
            errors.append(f"index_{idx}_missing_local_files_section")
            continue
        if headings and "## 本地文件" not in text[headings[-1]:]:
            errors.append(f"index_{idx}_local_files_not_final_section")
        local = text[text.rfind("## 本地文件"):]
        for label in ("原视频", "转写稿", "音频"):
            match = re.search(rf"(?m)^- {label}: \[[^\]]+\]\(([^)]+)\)", local)
            if not match:
                errors.append(f"index_{idx}_missing_{label}_link")
            elif not (note.parent / match.group(1)).is_file():
                errors.append(f"index_{idx}_missing_{label}_asset")
    return len(selected), errors


def run_pipeline(p: dict[str, Path | str]) -> int:
    review_index = current_review_index(Path(p["review"]))
    reconcile_current_notes(p, review_index)
    selected, duplicates = selected_items(p)
    indices = sorted(int(item["index"]) for item in selected)
    log(p, f"pipeline_started new_candidates={len(indices)} existing_review_duplicates={len(duplicates)}")
    if not indices:
        log(p, "no_new_review_candidates; nothing_to_do")
        return 0

    for worker_run in range(1, 3):
        _, errors = completion_errors(p)
        pending = sorted({int(m.group(1)) for err in errors if (m := re.match(r"index_(\d+)_", err))})
        if not pending:
            break
        log(p, f"summary_worker_started run={worker_run}/2 pending={len(pending)}")
        retries = ["--request-attempts", "2", "--item-attempts", "2", "--failure-rounds", "2"] if worker_run == 1 else [
            "--request-attempts", "2", "--item-attempts", "1", "--failure-rounds", "1"
        ]
        run_stage(p, "summary_worker" if worker_run == 1 else "summary_worker_recovery", [
            sys.executable, str(SUMMARY), "--manifest", str(p["manifest"]),
            "--indices", *map(str, pending), *retries, "--continue-on-error",
        ], summary=True)

    _, errors = completion_errors(p)
    if errors:
        log(p, "completion_gate_failed=" + ",".join(errors))
        return 2

    organization_indices = indices_to_organize(p, selected)
    common = [
        sys.executable, str(ORGANIZER), "--output", str(p["output"]),
        "--manifest", str(p["manifest"]), "--pulled-at", str(p["pulled_at"]),
        "--indices", *map(str, organization_indices),
    ]
    if organization_indices:
        preview = run_stage(p, "organization_preview", common)
        preview_path = Path(p["json_dir"]) / "organization-preview.txt"
        preview_path.write_text(preview.stdout, encoding="utf-8")
        if preview.returncode:
            log(p, "organization_preview_failed")
            return 3
        rows = re.findall(r"^\[\d{4}-\d{2}-\d{2} ([^ #]+) #\d+\] .* -> ", preview.stdout, re.M)
        if len(rows) != len(organization_indices) or any(category not in ALLOWED_CATEGORIES for category in rows):
            log(p, f"organization_preview_gate_failed candidate_count={len(rows)}")
            return 3

        applied = run_stage(p, "organization_apply", common + ["--apply", "--allow-nonempty-current"])
        if applied.returncode:
            log(p, "organization_apply_failed")
            return 4
        review_index = current_review_index(Path(p["review"]))
        reconcile_current_notes(p, review_index)
    else:
        log(p, "organization_skipped_all_selected_notes_already_present_for_this_pull")
    filled = run_stage(p, "local_file_link_backfill", [
        sys.executable, str(BACKFILL), "--manifest", str(p["manifest"]),
        "--pull-id", str(p["pull_id"]), "--review-root", str(p["review"]),
        "--asset-root", str(Path(p["output"]) / "assets"), "--apply",
    ])
    if filled.returncode:
        log(p, "local_file_link_backfill_failed")
        return 5
    count, errors = verify_final(p)
    if errors:
        log(p, "final_verification_failed=" + ",".join(errors))
        return 6
    log(p, f"PIPELINE_COMPLETE summaries={count} candidates={count} existing_review_duplicates={len(duplicates)} local_assets_verified={count}")
    return 0


def main() -> int:
    args = parse_args()
    p = paths(args)
    Path(p["json_dir"]).mkdir(parents=True, exist_ok=True)
    if args.detach:
        return spawn_detached(args, p)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    lock_stream = Path(p["lock"]).open("w", encoding="utf-8")
    try:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("A review pipeline already holds the manifest lock.", file=sys.stderr)
        return 2
    Path(p["pid"]).write_text(f"{os.getpid()}\n", encoding="utf-8")
    try:
        return run_pipeline(p)
    finally:
        try:
            Path(p["pid"]).unlink()
        except FileNotFoundError:
            pass
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
        lock_stream.close()


if __name__ == "__main__":
    raise SystemExit(main())
