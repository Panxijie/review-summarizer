#!/usr/bin/env python3
"""Append canonical local video or image evidence links to Douyin review notes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from note_metadata import render_frontmatter, split_frontmatter
from organize_content_library import local_file_section, strip_local_file_section


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
    by_index = {str(item.get("index")): item for item in manifest}
    by_url = {str(item.get("source_url") or item.get("url")): item for item in manifest}
    changed = missing = 0
    for note in sorted(args.review_root.rglob("*.md")):
        text = note.read_text(encoding="utf-8", errors="ignore")
        meta, body = split_frontmatter(text)
        if str(meta.get("pull_id")) != args.pull_id:
            continue
        index = meta.get("manifest_item_index")
        item = by_index.get(str(index)) if index is not None else by_url.get(str(meta.get("source_url")))
        if not item:
            print(f"skip {note}: source URL absent from manifest")
            missing += 1
            continue
        images = item.get("images") or []
        if images:
            assets = {"transcript": str(item.get("transcript") or "")}
            if not all(Path(path).is_file() for path in [*images, assets["transcript"]]):
                print(f"skip {note}: missing original image or OCR text")
                missing += 1
                continue
        else:
            stem = note.stem
            assets = {
                "video": first_existing([Path(str(item.get("video") or "")), *args.asset_root.joinpath("video").glob(f"{stem}-video.*")]),
                "transcript": first_existing([Path(str(item.get("transcript") or "")), *args.asset_root.joinpath("transcripts").glob(f"{stem}-transcript.*")]),
                "audio": first_existing([Path(str(item.get("audio") or "")), *args.asset_root.joinpath("audio").glob(f"{stem}-audio.*")]),
            }
            absent = [key for key, path in assets.items() if not path]
            if absent:
                print(f"skip {note}: missing {', '.join(absent)}")
                missing += 1
                continue
        section = local_file_section(note, {key: str(path) for key, path in assets.items()}, images)
        if args.apply:
            note.write_text(render_frontmatter(meta) + "\n\n" + strip_local_file_section(body) + "\n\n" + section + "\n", encoding="utf-8")
        print(f"updated {note}")
        changed += 1
    print(f"changed={changed} missing={missing}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
