#!/usr/bin/env python3
"""Shared filesystem layout helpers for Douyin review ingestion."""

from __future__ import annotations

from pathlib import Path


DEFAULT_OUTPUT = Path("Wiki Library/raw/originals/douyin")
# Candidate-review categories mirror the user-facing folders under
# raw/review/current.  Keep this list in sync with organize_content_library.
REVIEW_CATEGORIES = [
    "技术与工具",
    "科研与学习",
    "财务与资产",
    "职场与发展",
    "情感与关系",
    "日常与生活",
    "待分类",
]


def pulls_root(output: Path) -> Path:
    return output / "pulls"


def registry_root(output: Path) -> Path:
    return output / "registry"


def aweme_ids_path(output: Path) -> Path:
    legacy = output / "拉取记录" / "aweme_ids.txt"
    modern = registry_root(output) / "aweme_ids.txt"
    if legacy.exists() and not modern.exists():
        return legacy
    return modern


def manifest_candidates(output: Path) -> list[Path]:
    return [
        *sorted((pulls_root(output)).glob("*/json/run_manifest.json")),
        *sorted((output / "拉取记录").glob("*/json/run_manifest.json")),
    ]


def review_root(output: Path) -> Path:
    # Douyin media/pull records stay under raw/originals/douyin, but candidate
    # summaries use the shared raw/review queue for human triage.
    if output.name == "douyin":
        if output.parent.name == "originals":
            return output.parent.parent / "review"
        return output.parent / "review"
    return output / "review"


def review_current(output: Path) -> Path:
    return review_root(output) / "current"


def review_archive(output: Path) -> Path:
    return review_root(output) / "archive"


def review_events_path(output: Path) -> Path:
    return registry_root(output) / "review_events.jsonl"


def asset_root(output: Path) -> Path:
    return output / "assets"


def asset_dir(output: Path, kind: str) -> Path:
    mapping = {
        "video": "video",
        "audio": "audio",
        "transcript": "transcripts",
        "image": "images",
    }
    return asset_root(output) / mapping[kind]


def ensure_review_dirs(output: Path) -> None:
    for root in (review_current(output), review_archive(output)):
        for category in REVIEW_CATEGORIES:
            (root / category).mkdir(parents=True, exist_ok=True)
    registry_root(output).mkdir(parents=True, exist_ok=True)


def current_review_notes(output: Path) -> list[Path]:
    current = review_current(output)
    if not current.exists():
        return []
    return sorted(
        path
        for path in current.rglob("*.md")
        if path.is_file() and path.name != "README.md"
    )


def assert_current_review_empty(output: Path) -> None:
    notes = current_review_notes(output)
    if notes:
        sample = "\n".join(f"- {path}" for path in notes[:10])
        more = "" if len(notes) <= 10 else f"\n... and {len(notes) - 10} more"
        raise SystemExit(
            "Wiki Library/raw/review/current is not empty. "
            "Review, favorite, promote, or delete the current notes before starting a new pull:\n"
            f"{sample}{more}"
        )
