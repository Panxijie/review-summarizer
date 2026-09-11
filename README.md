# Review Summarizer

Codex skill for turning already-local source materials into human-reviewable Markdown notes for a Wiki Library workflow.

The skill starts from files that already exist under `raw/originals/` and writes candidate notes to `raw/review/current/`. It does not fetch web pages, log in to platforms, download media, or promote notes into a final wiki.

## What It Includes

- Material profiles for WeChat articles, general web articles, and Douyin videos.
- Prompt templates and an OpenAI-compatible model config template.
- Scripts for article summarization, Douyin transcript summarization, retry-safe manifest updates, parallel summary supervision, and review-note organization.
- Guardrails for keeping API keys, cookies, signed URLs, source text, and model responses out of logs and committed files.

## Repository Layout

- `SKILL.md`: Codex skill instructions and workflow rules.
- `summary_profiles/`: profile metadata, prompts, and model config templates.
- `scripts/`: summarization, organization, metadata, and manifest helper scripts.
- `agents/openai.yaml`: display metadata for the Codex skill.

## Setup

Clone or copy this repository into your Codex skills directory, for example:

```bash
~/.codex/skills/review-summarizer
```

Configure API access with environment variables. The default model config reads the key from `DEEPSEEK_API_KEY`; do not commit real keys into this repository.

On macOS with Codex Desktop, GUI apps may not inherit shell exports. Set the key for the login session with:

```zsh
launchctl setenv DEEPSEEK_API_KEY 'your-key-here'
```

Then fully quit and reopen Codex.

## Usage

For a local article:

```bash
python3 scripts/summarize_article_to_review.py \
  --wiki-root "Wiki Library" \
  --profile general-article \
  --input "Wiki Library/raw/originals/web/YYYY-MM-DD/article.md"
```

For a Douyin pull manifest created by `dy-faves-puller`:

```bash
python3 scripts/summarize_notes_with_model.py \
  --manifest "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/run_manifest.json"
```

Preview organization before applying:

```bash
python3 scripts/organize_content_library.py \
  --output "Wiki Library/raw/originals/douyin" \
  --manifest "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/run_manifest.json" \
  --pulled-at "YYYY-MM-DD HH:MM"
```

## Safety Notes

This repository is intended to contain reusable code, prompts, and templates only. Keep local source materials, transcripts, media files, logs, `.env` files, cookies, signed URLs, and model-provider secrets outside Git.

The included `.gitignore` excludes common local secret files, local model configs, logs, caches, and build output. If you create provider-specific configs with real credentials, use a `*.local.json`, `*-local.json`, or private ignored path.

## License

MIT
