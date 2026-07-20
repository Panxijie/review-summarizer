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

## DeepSeek Key in Codex Desktop (macOS)

Before a DeepSeek call, check only whether the configured key environment variable exists; never print its value. If the configured `api_key_env` is missing, do not send local materials or ask the user to paste the key into chat.

For Codex desktop on macOS, explain that a shell `export` does not modify an already-running GUI app. Ask the user to run this in Terminal, replacing the placeholder locally:

```zsh
launchctl setenv DEEPSEEK_API_KEY 'your-key-here'
```

Then ask them to fully quit Codex with Command-Q and reopen it before retrying. This makes the variable available to subsequently launched GUI apps for the current login session. Do not put the key in the vault, repository, skill files, command output, or chat.

To remove the variable later, provide:

```zsh
launchctl unsetenv DEEPSEEK_API_KEY
```

After the user restarts Codex, re-check only whether the variable exists. If it is still absent, report that the Codex process has not inherited the environment variable and ask the user to confirm the launch/restart; never search user configuration files or reveal secrets.

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

### Completion gate before organization

Do not run `organize_content_library.py --apply` merely because the summarizer has started. First wait for every selected model call to exit successfully, then verify each eligible record (`status: ok` with readable `note` and `transcript`) has:

- `summary_model` and `summary_generated_at` recorded in the manifest;
- `## 摘要`, `## 详细内容`, and `## 注意事项` in its note body; and
- no fallback headings such as `## 内容脉络（自动提取）` or `## 整理状态`.

If any record is missing, stale, or invalid, keep it out of review and repair or retry it before organization. Treat a process timeout or a detached process with incomplete logs as incomplete, not as a successful summary run.

For long manifests, summarize one index or a small bounded batch at a time with `--indices`, using a durable local job rather than one foreground serial command. Give each model call time to reach the configured request timeout, verify the batch result, then continue. Do not run concurrent writers against the same manifest; use separate shard manifests or sequential calls.

When a pull reuses prior assets or review notes, match records by the pair `(pull_id, manifest_item_index)`, never by `manifest_item_index` alone. Confirm the selected note and transcript paths exist before sending them to the model; if they do not, rebuild a pull-scoped repair manifest instead of silently skipping the item or modifying a note from another pull.

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

If `raw/review/current/` already contains notes, append only when the user explicitly authorizes merging into that batch; then add `--allow-nonempty-current`. This permission does not waive the completion gate above.

The apply pass writes candidate notes under `Wiki Library/raw/review/current/<category>/`, moves local source assets into `Wiki Library/raw/originals/douyin/assets/`, and updates the manifest with final paths.

### Douyin review 分类规则

候选笔记只使用现有的细分目录：`技术与工具`、`科研与学习`、`财务与资产`、`职场与发展`、`情感与关系`、`日常与生活` 和 `待分类`；不得重新创建或使用 `生活与职场`、`职场发展`、`日常生活` 或 `影音与娱乐`。

- 金融、财经、宏观经济、汇率、货币、银行、房地产、投资与资产配置归入 `财务与资产`。
- 阅读、书籍、宗教、法律、法学和司法相关内容归入 `科研与学习`。
- 影音与娱乐内容由 `dy-faves-puller` 标记为 `skipped_entertainment`，保留在拉取清单中但不生成 review 候选或 `current` 分类目录。
- 仅在无法根据标题、标签和正文可靠判断时，才使用 `待分类`。

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
- `## 本地文件` when local media or transcript assets exist. For each successfully processed video, this section must be the final section and link to all three local files: MP4 (`原视频`), transcript (`转写稿`), and audio (`音频`). A model refresh must preserve this section; if it is absent, run `scripts/backfill_douyin_local_file_links.py` against the pull manifest before delivery.

Do not optimize for the shortest possible note. Preserve examples, steps, settings, comparisons, names, numbers, claims, caveats, and reusable phrasing when they are present in the source.

## Review Boundary

This skill stops after writing candidate notes to `raw/review/current/`. Do not create source pages, update outputs, or promote notes into `Wiki Library/wiki/` here. The reader decides value by deleting, moving to `raw/favorites/`, or leaving notes in review.

## Resources

- `summary_profiles/`: material-type profiles, prompts, and model config templates. Do not store real API keys here; use environment variables.
- `scripts/summarize_article_to_review.py`: summarizes one local article-like file using a profile from `summary_profiles/`.
- `scripts/summarize_notes_with_model.py`: rewrites Douyin staging note bodies from manifest transcripts.
- `scripts/organize_content_library.py`: organizes Douyin notes into `raw/review/current/` and moves assets into `raw/originals/douyin/assets/`.
- `scripts/note_metadata.py` and `scripts/douyin_layout.py`: helpers for Douyin manifest workflows.
