#!/usr/bin/env python3
"""Organize Douyin notes separately from flat local media assets."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from douyin_layout import (
    DEFAULT_OUTPUT,
    asset_dir,
    assert_current_review_empty,
    ensure_review_dirs,
    manifest_candidates,
    pulls_root,
    review_archive,
    review_current,
)
from note_metadata import compact_content_type, compact_count, render_frontmatter, split_frontmatter, stats_from_aweme, tags_from_aweme


CATEGORY_RULES = [
    ("技术与工具", r"Codex|AI|Agent|Skill|插件|模型|软件|工具|电脑|VPN|零信任|网络|编程|服务器|NAS|Transformer|Attention"),
    ("科研与学习", r"科研|论文|学术|基金申报|文献|学习方法|课程|教育|大学|录取|考研|英语|阅读|读书|书籍|书单|好书|文学|宗教|佛教|道教|基督教|神学|法律|法学|刑法|民法|司法|判例"),
    ("财务与资产", r"财富|理财|投资|基金|股票|纳斯达克|纳指|定投|资产配置|财务自由|攒钱|花钱|搞钱|富人思维|消费观|现金流|负债|储蓄|止盈|止损|回撤|ETF|QDII|金融|财经|经济|汇率|货币|银行|房地产|房价"),
    ("职场与发展", r"职场|求职|就业|职业选择|职业规划|岗位|面试|HR|背调|大厂|校招|春招|offer|工作经验|投简历|LeetCode|力扣|机考|笔试"),
    ("日常与生活", r"生活经验|消费|购物|健康|减脂|营养|护肤|穿搭|香水|手机壳|数码配件|摄影|构图|秃|脱发|黑头|假货|验货|添柏岚|汽车|汽油|发动机|燃油|装修|家装|智能家居|家电|家具|茶叶|茶文化|茶生活|线香"),
    ("情感与关系", r"恋爱|择偶|爱情|情感|婚姻|伴侣|NPD|人格|亲密关系|暧昧|约会|撩|聊天技巧"),
]


def slugify(value: str, fallback: str) -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value, flags=re.UNICODE).strip("-._")
    return (value[:70] or fallback).strip("-._")


def classify(title: str, tags: list[str], body: str) -> tuple[str, str]:
    primary = "\n".join([title, " ".join(map(str, tags))])
    classification_text = f"{primary}\n{body[:800]}"
    category = next((name for name, pattern in CATEGORY_RULES if re.search(pattern, primary, re.I)), None)
    if not category:
        # Body text can mention platform tags such as “视频播客扶持计划”; keep this fallback narrow.
        category = next((name for name, pattern in CATEGORY_RULES if re.search(pattern, body[:800], re.I)), "待分类")
    if category == "技术与工具":
        if re.search(r"VPN|零信任|网络|服务器|NAS", primary, re.I):
            return category, "编程与网络"
        if re.search(r"软件|电脑技巧|LocalSend|Everything|Bandizip", primary, re.I):
            return category, "软件工具"
        return category, "AI与自动化"
    if category == "科研与学习":
        return category, "科研与学习"
    if category == "财务与资产":
        if re.search(r"经济|汇率|货币|银行|房地产|房价|宏观", classification_text, re.I):
            return category, "宏观经济与市场"
        return category, "个人财务与资产配置"
    if category == "情感与关系":
        return category, "人际心理" if re.search(r"NPD|人格|操控|心理", primary, re.I) else "恋爱择偶"
    if category == "职场与发展":
        if re.search(r"背调", primary, re.I):
            return category, "背调与求职规则"
        if re.search(r"LeetCode|力扣|Attention|机考|笔试|算法|大模型面试", primary, re.I):
            return category, "技术面试"
        if re.search(r"面试|HR|offer", primary, re.I):
            return category, "面试表达"
        if re.search(r"就业|职业|岗位|求职|投简历|校招|春招", primary, re.I):
            return category, "求职与职业规划"
        return category, "职场信息"
    if category == "日常与生活":
        if re.search(r"减脂|营养|蛋白质|饮食", primary, re.I):
            return category, "饮食与健康"
        if re.search(r"护肤|黑头|秃|脱发", primary, re.I):
            return category, "护肤与个人护理"
        if re.search(r"穿搭|衣服|鞋|靴|添柏岚|假货|验货", primary, re.I):
            return category, "穿搭选购"
        if re.search(r"香水", primary, re.I):
            return category, "香水选购"
        if re.search(r"手机壳|数码配件", primary, re.I):
            return category, "数码配件"
        if re.search(r"摄影|构图", primary, re.I):
            return category, "摄影与审美"
        return category, "生活经验"
    return category, "待分类"


def find_manifest(output: Path, explicit: Path | None) -> Path:
    if explicit:
        return explicit
    root = output / "run_manifest.json"
    if root.exists():
        return root
    candidates = sorted(manifest_candidates(output))
    if candidates:
        return candidates[-1]
    raise FileNotFoundError("No run_manifest.json found")


def parse_pulled_at(value: str | None, manifest: list[dict], manifest_path: Path) -> datetime:
    if value:
        return datetime.strptime(value, "%Y-%m-%d %H:%M")
    if manifest and manifest[0].get("pulled_at"):
        return datetime.strptime(str(manifest[0]["pulled_at"]), "%Y-%m-%d %H:%M")
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})", manifest_path.parent.parent.name)
    if match:
        return datetime.strptime(f"{match.group(1)} {match.group(2)}:{match.group(3)}", "%Y-%m-%d %H:%M")
    return datetime.fromtimestamp(manifest_path.stat().st_mtime).replace(second=0, microsecond=0)


def load_title_overrides(path: Path | None) -> dict[str, str]:
    if not path:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(key): str(value).strip() for key, value in raw.items() if str(value).strip()}


def summary_title(item: dict, meta: dict, fallback: str, overrides: dict[str, str]) -> str:
    for key in (str(item.get("index")), item.get("source_url"), item.get("url"), fallback):
        if key and str(key) in overrides:
            return overrides[str(key)]
    for key in ("summary_title", "note_title"):
        if meta.get(key):
            return str(meta[key]).strip()
    return fallback


def iter_existing_note_names(output: Path, category: str) -> list[Path]:
    review_paths: list[Path] = []
    for root in (review_archive(output), review_current(output)):
        note_root = root / category
        if note_root.exists():
            review_paths.extend(sorted(note_root.glob("*.md")))
    if review_paths:
        return sorted(review_paths)
    note_root = output / "笔记库" / category
    if note_root.exists():
        return sorted(note_root.glob("*.md"))
    legacy_root = output / "内容库" / category
    if legacy_root.exists():
        return sorted(legacy_root.glob("*/*.md"))
    return []


def existing_category_max(output: Path, pull_date: str, category: str, current_notes: set[Path]) -> int:
    maximum = 0
    pattern = re.compile(rf"^{re.escape(pull_date)}-(\d+)-")
    for path in iter_existing_note_names(output, category):
        if path.resolve() in current_notes:
            continue
        match = pattern.match(path.name)
        if match:
            maximum = max(maximum, int(match.group(1)))
    return maximum


def move_file(source_value: str | None, target: Path, apply: bool) -> str | None:
    if not source_value:
        return None
    source = Path(source_value)
    if not source.exists():
        raise FileNotFoundError(source)
    if source.resolve() == target.resolve():
        return str(target)
    if target.exists():
        raise FileExistsError(f"Target already exists: {target}")
    if apply:
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)
    return str(target)


def find_aweme(value: object, predicate) -> dict | None:
    if isinstance(value, dict):
        if predicate(value):
            return value
        for child in value.values():
            found = find_aweme(child, predicate)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_aweme(child, predicate)
            if found:
                return found
    return None


def stats_from_detail_json(path: str | None) -> dict[str, int]:
    if not path:
        return {}
    detail_path = Path(path)
    if not detail_path.exists():
        return {}
    try:
        data = json.loads(detail_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    aweme = find_aweme(data, lambda item: isinstance(item.get("statistics"), dict))
    return stats_from_aweme(aweme or {})


def tags_from_detail_json(path: str | None) -> list[str]:
    if not path:
        return []
    detail_path = Path(path)
    if not detail_path.exists():
        return []
    try:
        data = json.loads(detail_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    aweme = find_aweme(data, lambda item: "text_extra" in item or "desc" in item)
    return tags_from_aweme(aweme or {})


def ffprobe_duration_ms(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    try:
        return int(round(float(result.stdout.strip()) * 1000))
    except ValueError:
        return None


def format_duration(value: object, video_path: Path | None = None) -> str | None:
    milliseconds: int | None = None
    if isinstance(value, str) and re.search(r"小时|分钟|秒", value):
        return value
    if isinstance(value, (int, float)):
        milliseconds = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        milliseconds = int(value.strip())
    if milliseconds is None and video_path:
        milliseconds = ffprobe_duration_ms(video_path)
    if milliseconds is None:
        return None
    seconds = max(0, int(round(milliseconds / 1000)))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} 小时")
    if minutes:
        parts.append(f"{minutes} 分钟")
    if secs or not parts:
        parts.append(f"{secs} 秒")
    return " ".join(parts)


def strip_local_file_section(body: str) -> str:
    return re.sub(r"\n*## 本地文件\n(?:.*?)(?=\n## |\Z)", "\n\n", body, flags=re.S).strip()


def strip_transcript_section(body: str) -> str:
    return re.sub(r"\n*## Transcript\n(?:.*?)(?=\n## |\Z)", "\n\n", body, flags=re.S).strip()


def rel_link(note: Path, target: str) -> str:
    return Path(os.path.relpath(target, start=note.parent)).as_posix()


def local_file_section(note_target: Path, moved: dict[str, str]) -> str:
    labels = [
        ("video", "原视频"),
        ("image", "原图"),
        ("transcript", "转写稿"),
        ("audio", "音频"),
    ]
    lines = ["## 本地文件"]
    for key, label in labels:
        if moved.get(key):
            target = moved[key]
            lines.append(f"- {label}: [{Path(target).name}]({rel_link(note_target, target)})")
    return "\n".join(lines)


def insert_local_file_section(body: str, section: str) -> str:
    body = strip_transcript_section(strip_local_file_section(body))
    if not section:
        return body
    return body.rstrip() + "\n\n" + section


def update_legacy_links(body: str, moved: dict[str, str], note_target: Path) -> str:
    if moved.get("transcript"):
        body = re.sub(r"\]\((?:\.\./)?transcripts/[^)]+\)", f"]({rel_link(note_target, moved['transcript'])})", body)
        body = body.replace("](transcript.txt)", f"]({rel_link(note_target, moved['transcript'])})")
    if moved.get("image"):
        body = re.sub(r"`Douyin Favorites/downloads/[^`]+`", f"[{Path(moved['image']).name}]({rel_link(note_target, moved['image'])})", body)
        body = re.sub(r"`Douyin Favorites/内容库/[^`]+/image\.[^`]+`", f"[{Path(moved['image']).name}]({rel_link(note_target, moved['image'])})", body)
    return body


def build_meta(
    meta: dict,
    *,
    original_title: str,
    note_title: str,
    category: str,
    subcategory: str,
    pulled_at: datetime,
    sequence: int,
    pull_id: str,
    manifest_item_index: int,
    aweme_id: str | None,
    record_dir: Path,
    moved: dict[str, str],
    duration: str | None,
) -> dict:
    skipped = meta.get("transcription_skipped")
    if isinstance(skipped, str):
        skipped = skipped.lower() == "true"
    detail_stats = stats_from_detail_json(moved.get("detail_json") or meta.get("detail_json"))
    for key, value in detail_stats.items():
        if key in {"likes", "comments", "favorites", "shares"} and compact_count(meta.get(key)) is None:
            meta[key] = value
    detail_tags = tags_from_detail_json(moved.get("detail_json") or meta.get("detail_json"))
    if detail_tags and not meta.get("tags"):
        meta["tags"] = detail_tags
    return {
        "source_url": meta.get("source_url"),
        "aweme_id": aweme_id,
        "pull_id": pull_id,
        "pulled_at": pulled_at.strftime("%Y-%m-%d %H:%M"),
        "manifest_item_index": manifest_item_index,
        "promoted": False,
        "created_at": meta.get("created_at"),
        "content_type": compact_content_type(meta.get("content_type")),
        "original_title": meta.get("original_title") or original_title,
        "category": category,
        "subcategory": subcategory,
        "category_sequence": sequence,
        "duration": duration,
        "likes": compact_count(meta.get("likes")),
        "comments": compact_count(meta.get("comments")),
        "favorites": compact_count(meta.get("favorites")),
        "shares": compact_count(meta.get("shares")),
        "tags": meta.get("tags") if isinstance(meta.get("tags"), list) else [],
    }


def optional_source(explicit: Path | None, candidates: list[Path]) -> Path | None:
    if explicit:
        return explicit if explicit.exists() else None
    return next((path for path in candidates if path.exists()), None)


def cleanup_empty_dirs(paths: list[Path], output: Path, apply: bool) -> None:
    if not apply:
        return
    for path in sorted({p for p in paths if p.exists() and p.is_dir()}, key=lambda p: len(p.parts), reverse=True):
        current = path
        while current.exists() and current.is_dir() and current != output:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--pulled-at", help="Pull start time in YYYY-MM-DD HH:MM format.")
    parser.add_argument("--favorites-json", type=Path)
    parser.add_argument("--note-extracts", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--note-title-overrides", type=Path, help="JSON mapping index, URL, or original title to a summary-based note title.")
    parser.add_argument("--apply", action="store_true", help="Apply moves. Default is a preview.")
    parser.add_argument("--allow-nonempty-current", action="store_true", help="Append into raw/review/current even when it already contains review notes.")
    args = parser.parse_args()

    if args.apply:
        if not args.allow_nonempty_current:
            assert_current_review_empty(args.output)
        ensure_review_dirs(args.output)
    manifest_path = find_manifest(args.output, args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    title_overrides = load_title_overrides(args.note_title_overrides)
    pulled_at = parse_pulled_at(args.pulled_at, manifest, manifest_path)
    pull_date = pulled_at.strftime("%Y-%m-%d")
    record_dir = pulls_root(args.output) / pulled_at.strftime("%Y-%m-%d_%H-%M")
    json_dir = record_dir / "json"
    detail_dir = json_dir / "details"
    note_root = review_current(args.output)
    current_notes = {Path(item["note"]).resolve() for item in manifest if item.get("note") and Path(item["note"]).exists()}
    category_sequences: dict[str, int] = {}
    planned_targets: set[Path] = set()
    cleanup_candidates: list[Path] = []

    for item in manifest:
        index = int(item["index"])
        if not item.get("note"):
            print(f"[{index:02d}] {item.get('status')}")
            continue
        note_source = Path(item["note"])
        note_text = note_source.read_text(encoding="utf-8")
        meta, body = split_frontmatter(note_text)
        original_title = str(meta.get("original_title") or meta.get("title") or item.get("note_title") or item.get("title") or f"douyin-{index:02d}")
        note_title = summary_title(item, meta, original_title, title_overrides)
        tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
        inferred_category, inferred_subcategory = classify(original_title + "\n" + note_title, tags, body)
        category = str(meta.get("category") or inferred_category)
        subcategory = str(meta.get("subcategory") or inferred_subcategory)
        if category not in category_sequences:
            category_sequences[category] = existing_category_max(args.output, pull_date, category, current_notes)
        category_sequences[category] += 1
        sequence = category_sequences[category]
        stem = f"{pull_date}-{sequence:02d}-{slugify(note_title, f'douyin-{index:02d}')}"
        note_target = note_root / category / f"{stem}.md"
        if note_target in planned_targets:
            raise RuntimeError(f"Duplicate target: {note_target}")
        planned_targets.add(note_target)
        print(f"[{pull_date} {category} #{sequence:02d}] {subcategory} -> {note_target}")

        destinations = {
            "video": asset_dir(args.output, "video") / f"{stem}-video{Path(item['video']).suffix}" if item.get("video") else None,
            "audio": asset_dir(args.output, "audio") / f"{stem}-audio{Path(item['audio']).suffix}" if item.get("audio") else None,
            "transcript": asset_dir(args.output, "transcript") / f"{stem}-transcript.txt" if item.get("transcript") else None,
            "image": asset_dir(args.output, "image") / f"{stem}-image{Path(item['image']).suffix}" if item.get("image") else None,
            "detail_json": detail_dir / f"{stem}.json" if item.get("detail_json") else None,
        }
        moved: dict[str, str] = {}
        for key, target in destinations.items():
            if target:
                value = move_file(item.get(key), target, args.apply)
                if value:
                    moved[key] = value

        duration = format_duration(meta.get("duration") or item.get("duration") or item.get("duration_ms"), Path(moved["video"]) if moved.get("video") else None)
        meta = build_meta(
            meta,
            original_title=original_title,
            note_title=note_title,
            category=category,
            subcategory=subcategory,
            pulled_at=pulled_at,
            sequence=sequence,
            pull_id=record_dir.name,
            manifest_item_index=index,
            aweme_id=item.get("aweme_id"),
            record_dir=record_dir,
            moved=moved,
            duration=duration,
        )
        body = update_legacy_links(body, moved, note_target)
        section_assets = {key: value for key, value in moved.items() if key in {"video", "image", "transcript", "audio"}}
        body = insert_local_file_section(body, local_file_section(note_target, section_assets) if section_assets else "")

        old_note_dir = note_source.parent
        old_bundle = Path(item["bundle"]) if item.get("bundle") else old_note_dir
        cleanup_candidates.extend([old_note_dir, old_bundle])
        if args.apply:
            note_target.parent.mkdir(parents=True, exist_ok=True)
            note_target.write_text(render_frontmatter(meta) + "\n\n" + body.rstrip() + "\n", encoding="utf-8")
            if note_source.resolve() != note_target.resolve():
                note_source.unlink()

        item.update(moved)
        item.update({
            "note": str(note_target),
            "bundle": str(note_target.parent),
            "note_root": str(note_root),
            "asset_root": str(asset_dir(args.output, "video").parent),
            "note_title": note_title,
            "original_title": original_title,
            "category": category,
            "subcategory": subcategory,
            "pulled_at": pulled_at.strftime("%Y-%m-%d %H:%M"),
            "pull_id": record_dir.name,
            "pull_date": pull_date,
            "daily_sequence": sequence,
            "category_sequence": sequence,
            "duration": duration,
            "pull_record": str(record_dir),
        })

    record_sources = {
        "favorites_urls.json": optional_source(args.favorites_json, [manifest_path.parent / "favorites_urls.json", args.output / "favorites_urls.json"]),
        "note-extracts.json": optional_source(args.note_extracts, [manifest_path.parent / "note-extracts.json", args.output / "note-extracts.json"]),
    }
    report_source = optional_source(args.report, [record_dir / "run_report.md", args.output / "run_report.md"])
    if args.apply:
        json_dir.mkdir(parents=True, exist_ok=True)
        for name, source in record_sources.items():
            if source:
                move_file(str(source), json_dir / name, True)
        if report_source:
            move_file(str(report_source), record_dir / "run_report.md", True)
        target_manifest = json_dir / "run_manifest.json"
        target_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if manifest_path.resolve() != target_manifest.resolve():
            manifest_path.unlink()
        cleanup_empty_dirs(cleanup_candidates, args.output, True)
    else:
        print(f"Pull record -> {record_dir}")
        print("Preview only; rerun with --apply to organize files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
