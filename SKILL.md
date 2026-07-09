---
name: review-summarizer
description: Summarize local source materials into candidate Markdown review notes for Wiki Library. Use when Codex needs to take materials under `Wiki Library/raw/originals/` such as WeChat articles, web articles, newsletters, Douyin pull manifests, transcripts, or other captured sources, select the matching summary profile from this skill's `summary_profiles/`, call the configured OpenAI-compatible summary model, and write human-reviewable notes into `Wiki Library/raw/review/current/`.
---

# Review Summarizer

## Overview

Generate candidate review notes from already-local source materials. This skill does not fetch web pages, log in to platforms, download media, capture Douyin detail JSON, or promote anything into `Wiki Library/wiki/`. It starts from `raw/originals/` and stops at `raw/review/current/`.

Use this skill after a capture/intake skill has created local originals. For Douyin, run `dy-faves-puller` first and then summarize the resulting pull manifest here. For WeChat, web articles, newsletters, or manually clipped text, place the original in `raw/originals/<source>/...` first, then summarize it here.

## Profile Selection

Before calling a model, read:

```bash
Codex Skills/review-summarizer/summary_profiles/index.md
```

Choose the matching profile:

- `wechat-article`: WeChat public-account articles, manually clipped WeChat text, article-like WeChat exports.
- `general-article`: ordinary web articles, blogs, newsletters.
- `douyin-video`: Douyin favorite videos, image notes, and local transcripts from `dy-faves-puller`.

Use the selected profile's prompt and model config. Do not improvise a different prompt unless the user explicitly asks to change summary style. Do not print API keys, cookies, signed URLs, request bodies, model responses, or private source text.

## Preconditions

- The original material already exists under `Wiki Library/raw/originals/`.
- `Wiki Library/raw/review/current/` contains no pending Markdown notes except `README.md`, unless the user explicitly asks to add more into an existing review batch.
- The chosen profile has a prompt and model config.
- If the model call sends private local materials to an external API, the user has allowed that material to be sent.

## Article Workflow

Use this for WeChat, web articles, blogs, newsletters, and manually clipped text files.

```bash
python3 "Codex Skills/review-summarizer/scripts/summarize_article_to_review.py" \
  --wiki-root "Wiki Library" \
  --profile wechat-article \
  --input "Wiki Library/raw/originals/wechat/<date>/<title>.md"
```

For ordinary web articles, use `--profile general-article`. The script reads the profile prompt, calls the configured model, validates required headings, and writes a candidate note to `Wiki Library/raw/review/current/`.

Useful optional flags:

- `--title`: override the review note title.
- `--source-url`: add or override the source URL in YAML.
- `--output`: explicit output path under `raw/review/current/`.
- `--dry-run`: validate and print the target path without writing.

## Douyin Workflow

Use this only after `dy-faves-puller` has produced a verified manifest:

```bash
Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/run_manifest.json
```

Run the model summarizer:

```bash
python3 "Codex Skills/review-summarizer/scripts/summarize_notes_with_model.py" \
  --manifest "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/run_manifest.json"
```

This rewrites only each staging note body below YAML frontmatter and preserves metadata such as `likes`, `comments`, `favorites`, `shares`, `tags`, `source_url`, `duration`, and `content_type`.

Preview organization:

```bash
python3 "Codex Skills/review-summarizer/scripts/organize_content_library.py" \
  --output "Wiki Library/raw/originals/douyin" \
  --manifest "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/run_manifest.json" \
  --pulled-at "YYYY-MM-DD HH:MM"
```

Apply only after the preview looks right:

```bash
python3 "Codex Skills/review-summarizer/scripts/organize_content_library.py" \
  --output "Wiki Library/raw/originals/douyin" \
  --manifest "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/run_manifest.json" \
  --pulled-at "YYYY-MM-DD HH:MM" \
  --apply
```

The apply pass writes candidate notes under `Wiki Library/raw/review/current/<category>/`, moves local source assets into `Wiki Library/raw/originals/douyin/assets/`, and updates the manifest with final paths.

## Review Note Requirements

All candidate notes should help the reader decide whether to delete, move to `raw/favorites/`, or leave for later wiki promotion.

Article notes must contain:

- `## 摘要`
- `## 详细内容`
- `## 注意事项`

Douyin notes must contain:

- `## 摘要`
- `## 详细内容`
- `## 注意事项`
- `## 本地文件` when local media or transcript assets exist

Do not optimize for the shortest possible note. Preserve examples, steps, settings, comparisons, names, numbers, claims, caveats, and reusable phrasing when they are present in the source.

## Review Boundary

This skill stops after writing candidate notes to `raw/review/current/`. Do not create source pages, update outputs, or promote notes into `Wiki Library/wiki/` here. The reader decides value by deleting, moving to `raw/favorites/`, or leaving notes in review.

## Resources

- `summary_profiles/`: material-type profiles, prompts, and model config templates. Do not store real API keys here; use environment variables.
- `scripts/summarize_article_to_review.py`: summarizes one local article-like file using a profile from `summary_profiles/`.
- `scripts/summarize_notes_with_model.py`: rewrites Douyin staging note bodies from manifest transcripts.
- `scripts/organize_content_library.py`: organizes Douyin notes into `raw/review/current/` and moves assets into `raw/originals/douyin/assets/`.
- `scripts/note_metadata.py` and `scripts/douyin_layout.py`: helpers for Douyin manifest workflows.
