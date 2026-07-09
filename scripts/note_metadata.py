#!/usr/bin/env python3
"""Shared title, statistics, tag, and YAML helpers for Douyin notes."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

from douyin_layout import aweme_ids_path


HASHTAG_RE = re.compile(r"#([^#\s]+)")
LEADING_METRIC_RE = re.compile(r"^\s*\d+(?:\.\d+)?(?:万|亿)?\s*(?:\r?\n)+")
COUNT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)(万|亿)?\s*$")
COMPACT_COUNT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)k\s*$", re.I)
COMPACT_W_COUNT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)w\s*$", re.I)
AWEME_ID_RE = re.compile(r"(?<!\d)(\d{16,20})(?!\d)")


def parse_count(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    compact_w = COMPACT_W_COUNT_RE.match(str(value or ""))
    if compact_w:
        return int(float(compact_w.group(1)) * 10_000)
    compact = COMPACT_COUNT_RE.match(str(value or ""))
    if compact:
        return int(float(compact.group(1)) * 1000)
    match = COUNT_RE.match(str(value or ""))
    if not match:
        return None
    multiplier = {None: 1, "万": 10_000, "亿": 100_000_000}[match.group(2)]
    return int(float(match.group(1)) * multiplier)


def compact_count(value: object) -> int | str | None:
    count = parse_count(value)
    if count is None:
        return None
    if count < 10_000:
        return count
    compact = count / 10_000
    text = f"{compact:.1f}".rstrip("0").rstrip(".")
    return f"{text}w"


def compact_content_type(value: object) -> str | None:
    text = str(value or "").strip()
    if text.startswith("douyin_"):
        text = text.removeprefix("douyin_")
    return text or None


def extract_aweme_id(*values: object) -> str | None:
    for value in values:
        if value in (None, ""):
            continue
        if isinstance(value, dict):
            found = extract_aweme_id(
                value.get("aweme_id"),
                value.get("group_id"),
                value.get("item_id"),
                value.get("source_url"),
                value.get("url"),
            )
            if found:
                return found
            continue
        match = AWEME_ID_RE.search(str(value))
        if match:
            return match.group(1)
    return None


def load_aweme_ids(output: Path) -> set[str]:
    path = aweme_ids_path(output)
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def save_aweme_ids(output: Path, ids: Iterable[str]) -> None:
    path = aweme_ids_path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = sorted({str(value).strip() for value in ids if str(value).strip()})
    path.write_text("\n".join(cleaned) + ("\n" if cleaned else ""), encoding="utf-8")


def add_aweme_id(output: Path, aweme_id: str | None) -> None:
    if not aweme_id:
        return
    ids = load_aweme_ids(output)
    ids.add(aweme_id)
    save_aweme_ids(output, ids)


def leading_metric(value: str) -> int | None:
    first = next((line.strip() for line in str(value or "").splitlines() if line.strip()), "")
    return parse_count(first)


def extract_tags(value: str) -> list[str]:
    return dedupe(match.group(1).strip("，。！？、,.!?;；:：") for match in HASHTAG_RE.finditer(value or ""))


def dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = str(value or "").strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def clean_title(value: str, fallback: str) -> str:
    original = str(value or "")
    value = LEADING_METRIC_RE.sub("", original, count=1)
    value = HASHTAG_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip(" -_—，。！？、,.!?;；:：")
    if value:
        return value
    tags = extract_tags(original)
    return max(tags, key=len) if tags else fallback


def tags_from_aweme(aweme: dict) -> list[str]:
    structured = [
        item.get("hashtag_name")
        for item in aweme.get("text_extra") or []
        if isinstance(item, dict) and item.get("hashtag_name")
    ]
    return dedupe([*structured, *extract_tags(aweme.get("desc") or "")])


def stats_from_aweme(aweme: dict) -> dict[str, int]:
    stats = aweme.get("statistics") or {}
    mapping = {
        "likes": "digg_count",
        "comments": "comment_count",
        "favorites": "collect_count",
        "shares": "share_count",
        "plays": "play_count",
    }
    return {
        target: int(stats[source])
        for target, source in mapping.items()
        if stats.get(source) not in (None, "", 0)
    }


def yaml_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, Path):
        return json.dumps(str(value), ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def render_frontmatter(meta: dict) -> str:
    lines = ["---"]
    for key, value in meta.items():
        lines.append(f"{key}: {yaml_value(value)}")
    lines.append("---")
    return "\n".join(lines)


def split_frontmatter(text: str) -> tuple[dict, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        return {}, text
    meta: dict = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        raw = raw.strip()
        try:
            value = json.loads(raw)
        except Exception:
            value = raw
        meta[key.strip()] = value
    body = "\n".join(lines[end + 1:]).lstrip("\n")
    return meta, body
