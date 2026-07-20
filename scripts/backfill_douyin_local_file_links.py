#!/usr/bin/env python3
"""Append canonical local video, transcript, and audio links to Douyin review notes."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from note_metadata import render_frontmatter, split_frontmatter


def replace_local_section(body: str, section: str) -> str:
    body = re.sub(r"\n*## 本地文件\n(?:.*?)(?=\n## |\Z)", "\n\n", body, flags=re.S).strip()
    return body.rstrip() + "\n\n" + section + "\n"


def rel(note: Path, asset: Path) -> str:
    return Path(os.path.relpath(asset, note.parent)).as_posix()


def first_existing(candidates: list[Path]) -> Path | None:
    return next((path for path in candidates if path.is_file()), None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--pull-id", required=True)
    parser.add_argument("--review-root", required=True, type=Path)
    parser.add_argument("--asset-root", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    by_url = {str(item.get("source_url") or item.get("url")): item for item in manifest}
    changed = missing = 0
    for note in sorted(args.review_root.rglob("*.md")):
        text = note.read_text(encoding="utf-8", errors="ignore")
        meta, body = split_frontmatter(text)
        if str(meta.get("pull_id")) != args.pull_id:
            continue
        item = by_url.get(str(meta.get("source_url")))
        if not item:
            print(f"skip {note}: source URL absent from manifest")
            missing += 1
            continue
        stem = note.stem
        assets = {
            "原视频": first_existing([Path(str(item.get("video") or "")), *args.asset_root.joinpath("video").glob(f"{stem}-video.*")]),
            "转写稿": first_existing([Path(str(item.get("transcript") or "")), *args.asset_root.joinpath("transcripts").glob(f"{stem}-transcript.*")]),
            "音频": first_existing([Path(str(item.get("audio") or "")), *args.asset_root.joinpath("audio").glob(f"{stem}-audio.*")]),
        }
        absent = [label for label, path in assets.items() if not path]
        if absent:
            print(f"skip {note}: missing {', '.join(absent)}")
            missing += 1
            continue
        section = "## 本地文件\n" + "\n".join(
            f"- {label}: [{path.name}]({rel(note, path)})" for label, path in assets.items() if path
        )
        if args.apply:
            note.write_text(render_frontmatter(meta) + "\n\n" + replace_local_section(body, section), encoding="utf-8")
        print(f"updated {note}")
        changed += 1
    print(f"changed={changed} missing={missing}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
