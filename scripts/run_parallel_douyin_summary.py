#!/usr/bin/env python3
"""Run disjoint Douyin summary shards in parallel and merge through one writer."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from summarize_notes_with_model import (
    DEFAULT_CONFIG,
    acquire_manifest_lock,
    load_config,
    validate_body,
    write_manifest_atomic,
)


SCRIPT_DIR = Path(__file__).resolve().parent
SUMMARY_SCRIPT = SCRIPT_DIR / "summarize_notes_with_model.py"
SUMMARY_FIELDS = (
    "summary_model",
    "summary_generated_at",
    "summary_elapsed_seconds",
    "summary_api_calls",
    "summary_item_attempts",
)


def write_json_atomic(path: Path, value) -> None:
    temp_path = path.with_name(path.name + ".tmp")
    temp_path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def eligible_items(manifest: list[dict], wanted: set[int], required_model: str) -> list[dict]:
    return [
        item
        for item in manifest
        if item.get("status") == "ok"
        and (not wanted or int(item.get("index", 0)) in wanted)
        and (
            item.get("summary_model") != required_model
            or not item.get("summary_generated_at")
        )
    ]


def transcript_weight(item: dict) -> int:
    value = item.get("transcript")
    if not value:
        return 1
    path = Path(value)
    try:
        return max(1, path.stat().st_size)
    except OSError:
        return 1


def balanced_assignments(items: list[dict], workers: int) -> list[list[int]]:
    assignments = [[] for _ in range(workers)]
    totals = [0 for _ in range(workers)]
    for item in sorted(items, key=transcript_weight, reverse=True):
        worker = min(range(workers), key=lambda position: totals[position])
        assignments[worker].append(int(item.get("index", 0)))
        totals[worker] += transcript_weight(item)
    for indices in assignments:
        indices.sort()
    return assignments


def parse_worker_log(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    starts = re.findall(r"^\[(\d+)\] summarizing ([^\n]*)", text, re.M)
    completed = re.findall(
        r"^\[(\d+)\] completed elapsed_seconds=([0-9.]+) api_calls=(\d+) item_attempts=(\d+)",
        text,
        re.M,
    )
    failures = re.findall(r"^\[(\d+)\] failed [^\n]* error=([A-Za-z0-9]+)", text, re.M)
    rounds = re.findall(r"^retry_round=([^\n]+)", text, re.M)
    return {
        "active_or_last_start": starts[-1] if starts else None,
        "last_completed": completed[-1] if completed else None,
        "last_error": failures[-1] if failures else None,
        "retry_round": rounds[-1] if rounds else "1",
    }


def valid_summary_item(item: dict, required_model: str) -> bool:
    if item.get("summary_model") != required_model or not item.get("summary_generated_at"):
        return False
    note_value = item.get("note")
    if not note_value:
        return False
    note_path = Path(note_value)
    if not note_path.exists():
        return False
    try:
        validate_body(note_path.read_text(encoding="utf-8", errors="ignore"), note_path)
    except RuntimeError:
        return False
    return True


def merge_shards(main_path: Path, shard_paths: list[Path], selected: set[int], required_model: str) -> set[int]:
    main_manifest = json.loads(main_path.read_text(encoding="utf-8"))
    main_by_index = {int(item.get("index", 0)): item for item in main_manifest}
    merged: set[int] = set()
    changed = False
    for shard_path in shard_paths:
        if not shard_path.exists():
            continue
        shard_manifest = json.loads(shard_path.read_text(encoding="utf-8"))
        for shard_item in shard_manifest:
            index = int(shard_item.get("index", 0))
            if index not in selected or index not in main_by_index:
                continue
            if not valid_summary_item(shard_item, required_model):
                continue
            main_item = main_by_index[index]
            for field in SUMMARY_FIELDS:
                if main_item.get(field) != shard_item.get(field):
                    main_item[field] = shard_item.get(field)
                    changed = True
            merged.add(index)
    if changed:
        write_manifest_atomic(main_path, main_manifest)
    for index in selected:
        item = main_by_index.get(index)
        if item and valid_summary_item(item, required_model):
            merged.add(index)
    return merged


def child_command(args, shard_path: Path, indices: list[int]) -> list[str]:
    command = [
        sys.executable,
        str(SUMMARY_SCRIPT),
        "--manifest",
        str(shard_path),
        "--config",
        str(args.config),
        "--indices",
        *[str(index) for index in indices],
        "--max-transcript-chars",
        str(args.max_transcript_chars),
        "--repair-attempts",
        str(args.repair_attempts),
        "--request-attempts",
        str(args.request_attempts),
        "--item-attempts",
        str(args.item_attempts),
        "--failure-rounds",
        str(args.failure_rounds),
        "--retry-delay-seconds",
        str(args.retry_delay_seconds),
        "--continue-on-error",
        "--require-model",
        args.require_model,
    ]
    return command


def start_children(args, work_dir: Path, manifest: list[dict], assignments: list[list[int]], label: str):
    children = []
    shard_paths = []
    for position, indices in enumerate(assignments, start=1):
        if not indices:
            continue
        shard_path = work_dir / f"{label}-worker-{position}.json"
        log_path = work_dir / f"{label}-worker-{position}.log"
        write_json_atomic(shard_path, manifest)
        log_handle = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            child_command(args, shard_path, indices),
            cwd=Path.cwd(),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        children.append(
            {
                "worker": position,
                "indices": indices,
                "process": process,
                "log_handle": log_handle,
                "log_path": log_path,
                "shard_path": shard_path,
            }
        )
        shard_paths.append(shard_path)
    return children, shard_paths


def stop_children(children) -> None:
    for child in children:
        process = child["process"]
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    for child in children:
        process = child["process"]
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        child["log_handle"].close()


def supervise(args, work_dir: Path, main_manifest: list[dict], assignments: list[list[int]], label: str):
    selected = {index for indices in assignments for index in indices}
    children, shard_paths = start_children(args, work_dir, main_manifest, assignments, label)
    interrupted = False

    def handle_signal(_signum, _frame):
        nonlocal interrupted
        interrupted = True

    previous_term = signal.signal(signal.SIGTERM, handle_signal)
    previous_int = signal.signal(signal.SIGINT, handle_signal)
    try:
        while not interrupted and any(child["process"].poll() is None for child in children):
            merged = merge_shards(args.manifest, shard_paths, selected, args.require_model)
            status = {
                "state": "running",
                "required_model": args.require_model,
                "selected_indices": sorted(selected),
                "merged_indices": sorted(merged),
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "workers": [
                    {
                        "worker": child["worker"],
                        "pid": child["process"].pid,
                        "returncode": child["process"].poll(),
                        "indices": child["indices"],
                        "progress": parse_worker_log(child["log_path"]),
                    }
                    for child in children
                ],
            }
            write_json_atomic(work_dir / "status.json", status)
            time.sleep(max(1.0, args.poll_seconds))
    finally:
        if interrupted:
            stop_children(children)
        else:
            for child in children:
                child["process"].wait()
                child["log_handle"].close()
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)

    merged = merge_shards(args.manifest, shard_paths, selected, args.require_model)
    return children, shard_paths, merged, interrupted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--indices", nargs="*", type=int)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--require-model", required=True)
    parser.add_argument("--max-transcript-chars", type=int, default=24000)
    parser.add_argument("--repair-attempts", type=int, default=5)
    parser.add_argument("--request-attempts", type=int, default=4)
    parser.add_argument("--item-attempts", type=int, default=3)
    parser.add_argument("--failure-rounds", type=int, default=4)
    parser.add_argument("--retry-delay-seconds", type=float, default=5.0)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--no-serial-fallback", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.workers < 1 or args.workers > 3:
        raise SystemExit("workers must be between 1 and 3")
    config = load_config(args.config)
    if config.get("model") != args.require_model:
        raise SystemExit("Configured model does not match --require-model")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    items = eligible_items(manifest, set(args.indices or []), args.require_model)
    assignments = balanced_assignments(items, args.workers)
    plan = {
        "required_model": args.require_model,
        "workers": args.workers,
        "selected_indices": sorted(int(item.get("index", 0)) for item in items),
        "assignments": assignments,
    }
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False))
        return 0
    if not items:
        print("No incomplete eligible items.")
        return 0

    _main_lock = acquire_manifest_lock(args.manifest)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(args.work_dir / "plan.json", plan)
    children, shard_paths, merged, interrupted = supervise(
        args,
        args.work_dir,
        manifest,
        assignments,
        "parallel",
    )
    selected = set(plan["selected_indices"])
    pending = sorted(selected - merged)

    if pending and not interrupted and not args.no_serial_fallback:
        current_manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        fallback_assignments = [pending]
        fallback_children, fallback_shards, fallback_merged, fallback_interrupted = supervise(
            args,
            args.work_dir,
            current_manifest,
            fallback_assignments,
            "fallback",
        )
        children.extend(fallback_children)
        shard_paths.extend(fallback_shards)
        merged.update(fallback_merged)
        interrupted = interrupted or fallback_interrupted
        pending = sorted(selected - merged)

    final_status = {
        "state": "interrupted" if interrupted else ("complete" if not pending else "incomplete"),
        "required_model": args.require_model,
        "selected_indices": sorted(selected),
        "merged_indices": sorted(merged),
        "pending_indices": pending,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "workers": [
            {
                "worker": child["worker"],
                "pid": child["process"].pid,
                "returncode": child["process"].returncode,
                "indices": child["indices"],
                "progress": parse_worker_log(child["log_path"]),
            }
            for child in children
        ],
    }
    write_json_atomic(args.work_dir / "status.json", final_status)
    if pending or interrupted:
        print("Parallel summary incomplete pending_indices=" + ",".join(str(index) for index in pending))
        return 1
    print(f"Parallel summary complete merged={len(merged)} model={args.require_model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
