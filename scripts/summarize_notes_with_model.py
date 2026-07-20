#!/usr/bin/env python3
"""Rewrite draft Douyin notes with a configurable chat-completion model."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv_loader import load_dotenv
from note_metadata import split_frontmatter, render_frontmatter


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = SKILL_ROOT / "summary_profiles" / "model_configs" / "openai-compatible-default.json"
DEFAULT_PROMPT = SKILL_ROOT / "summary_profiles" / "prompts" / "douyin-video.md"


def load_config(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Missing summary model config: {path}")
    config = json.loads(path.read_text(encoding="utf-8"))
    config.setdefault("provider", "openai_compatible")
    config.setdefault("endpoint", "/chat/completions")
    config.setdefault("temperature", 0.2)
    config.setdefault("max_tokens", 4096)
    config.setdefault("timeout_seconds", 120)
    return config


def load_system_prompt(config: dict, config_path: Path) -> str:
    inline = str(config.get("system_prompt") or "").strip()
    if inline:
        return inline
    prompt_value = str(config.get("prompt_path") or DEFAULT_PROMPT)
    prompt_path = Path(prompt_value)
    if not prompt_path.is_absolute():
        prompt_path = config_path.parent / prompt_path
    if not prompt_path.exists():
        raise SystemExit(f"Missing summary prompt: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8").strip()


def api_key_from_config(config: dict) -> str:
    explicit = str(config.get("api_key") or "").strip()
    if explicit:
        return explicit
    env_name = str(config.get("api_key_env") or "").strip()
    if env_name:
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    raise SystemExit("Missing API key. Set config.api_key or export the config.api_key_env environment variable.")


def endpoint_url(config: dict) -> str:
    base_url = str(config.get("base_url") or "").rstrip("/")
    endpoint = str(config.get("endpoint") or "/chat/completions")
    if not base_url:
        raise SystemExit("Missing config.base_url")
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        return endpoint
    return f"{base_url}/{endpoint.lstrip('/')}"


def chat_completion(config: dict, messages: list[dict[str, str]]) -> str:
    payload = {
        "model": config.get("model"),
        "messages": messages,
        "temperature": config.get("temperature", 0.2),
        "max_tokens": config.get("max_tokens", 4096),
    }
    if not payload["model"]:
        raise SystemExit("Missing config.model")
    for key in ("top_p", "presence_penalty", "frequency_penalty"):
        if key in config:
            payload[key] = config[key]
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        endpoint_url(config),
        data=data,
        headers={
            "Authorization": f"Bearer {api_key_from_config(config)}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=int(config.get("timeout_seconds", 120))) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Summary API error {exc.code}: {body}") from exc
    choices = result.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    text = result.get("output_text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    raise RuntimeError(f"Summary API returned no text: {json.dumps(result, ensure_ascii=False)[:1000]}")


def compact_transcript(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2].rstrip()
    tail = text[-max_chars // 2 :].lstrip()
    return f"{head}\n\n[中间转写过长，已截断]\n\n{tail}"


def validate_body(body: str, note_path: Path) -> None:
    for heading in ("## 摘要", "## 详细内容", "## 注意事项"):
        if heading not in body:
            raise RuntimeError(f"{note_path}: model output missing {heading}")
    if "## Summary" in body or "## 内容脉络（自动提取）" in body or "## Notes" in body:
        raise RuntimeError(f"{note_path}: model output still contains draft fallback headings")
    match = re.search(r"^## 摘要\s*$([\s\S]*?)(?=^##\s+|\Z)", body, re.M)
    if not match:
        raise RuntimeError(f"{note_path}: missing summary section")
    summary = "".join(match.group(1).split())
    if len(summary) > 50:
        raise RuntimeError(f"{note_path}: summary is {len(summary)} chars; must be <= 50")


def local_file_section(body: str) -> str:
    """Keep organizer-managed local asset links when refreshing a summary."""
    match = re.search(r"(?:^|\n)(## 本地文件\n.*?)(?=\n## |\Z)", body, re.S)
    return match.group(1).strip() if match else ""


def build_user_prompt(item: dict, meta: dict, transcript: str, max_chars: int) -> str:
    source_title = meta.get("original_title") or meta.get("title") or item.get("title") or ""
    fields = {
        "manifest_index": item.get("index"),
        "source_url": meta.get("source_url") or item.get("source_url") or item.get("url"),
        "original_title": source_title,
        "content_type": meta.get("content_type") or item.get("content_type"),
        "duration": meta.get("duration") or item.get("duration") or item.get("duration_ms"),
        "likes": meta.get("likes"),
        "comments": meta.get("comments"),
        "favorites": meta.get("favorites"),
        "shares": meta.get("shares"),
        "tags": meta.get("tags") or [],
    }
    transcript = compact_transcript(transcript, max_chars)
    return (
        "请把下面这条抖音收藏整理成最终 Markdown 笔记正文。\n\n"
        "元数据：\n"
        f"{json.dumps(fields, ensure_ascii=False, indent=2)}\n\n"
        "本地语音转写：\n"
        f"{transcript or '[无可用转写]'}\n"
    )


def rewrite_note(
    item: dict,
    config: dict,
    system_prompt: str,
    max_transcript_chars: int,
    dry_run: bool,
    repair_attempts: int,
) -> str | None:
    note_value = item.get("note")
    transcript_value = item.get("transcript")
    if not note_value or not transcript_value:
        return None
    note_path = Path(note_value)
    transcript_path = Path(transcript_value)
    if not note_path.exists() or not transcript_path.exists():
        return None
    note_text = note_path.read_text(encoding="utf-8")
    meta, previous_body = split_frontmatter(note_text)
    previous_local_files = local_file_section(previous_body)
    transcript = transcript_path.read_text(encoding="utf-8", errors="ignore")
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": build_user_prompt(item, meta, transcript, max_transcript_chars)},
    ]
    body = chat_completion(config, messages)
    for _attempt in range(repair_attempts + 1):
        try:
            validate_body(body, note_path)
            break
        except RuntimeError as exc:
            if _attempt >= repair_attempts:
                raise
            messages.extend([
                {"role": "assistant", "content": body},
                {
                    "role": "user",
                    "content": (
                        f"上一次输出不符合要求：{exc}\n"
                        "请只重新输出完整 Markdown 正文，保留 `## 摘要`、`## 详细内容`、`## 注意事项`，"
                        "`## 摘要` 必须压缩到 50 个中文字符以内。"
                    ),
                },
            ])
            body = chat_completion(config, messages)
    if not dry_run:
        final_body = body.rstrip()
        if previous_local_files:
            final_body += "\n\n" + previous_local_files
        note_path.write_text(render_frontmatter(meta) + "\n\n" + final_body + "\n", encoding="utf-8")
    return body


def main() -> int:
    load_dotenv(SKILL_ROOT / ".env")

    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--indices", nargs="*", type=int, help="Only summarize these manifest indices.")
    parser.add_argument("--max-transcript-chars", type=int, default=24000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--print-output", action="store_true", help="Print generated Markdown bodies to stdout.")
    parser.add_argument("--repair-attempts", type=int, default=1, help="Retry model output when validation fails.")
    args = parser.parse_args()

    config = load_config(args.config)
    system_prompt = load_system_prompt(config, args.config)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    wanted = set(args.indices or [])
    count = 0
    for item in manifest:
        index = int(item.get("index", 0))
        if wanted and index not in wanted:
            continue
        if item.get("status") != "ok":
            continue
        print(f"[{index}] summarizing", flush=True)
        body = rewrite_note(item, config, system_prompt, args.max_transcript_chars, args.dry_run, args.repair_attempts)
        if body is not None:
            count += 1
            if args.print_output:
                print(f"\n--- GENERATED NOTE BODY index={index} ---\n{body}\n--- END GENERATED NOTE BODY index={index} ---", flush=True)
            if not args.dry_run:
                item["summary_model"] = config.get("model")
                item["summary_generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            print(f"[{index}] skipped: missing note or transcript", flush=True)
    print(f"Summarized {count} notes with {config.get('model')}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
