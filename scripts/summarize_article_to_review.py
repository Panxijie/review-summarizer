#!/usr/bin/env python3
"""Summarize one local article-like original into Wiki Library raw/review/current."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_PROFILES_ROOT = Path(__file__).resolve().parents[1] / "summary_profiles"


def resolve_wiki_root(value: Path) -> Path:
    if value.exists():
        return value
    if value.name == "Wiki Library" and Path.cwd().name == "Wiki Library":
        return Path.cwd()
    raise SystemExit(f"Wiki root not found: {value}")


def read_json(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Missing JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_profile(profiles_root: Path, profile_id: str) -> tuple[dict, Path]:
    profile_path = profiles_root / "profiles" / f"{profile_id}.json"
    return read_json(profile_path), profile_path


def resolve_profile_path(profile_path: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = profile_path.parent / path
    return path.resolve()


def load_model_config(profile: dict, profile_path: Path) -> dict:
    config_path = resolve_profile_path(profile_path, profile["model_config_path"])
    config = read_json(config_path)
    config.setdefault("provider", "openai_compatible")
    config.setdefault("endpoint", "/chat/completions")
    config.setdefault("temperature", 0.2)
    config.setdefault("max_tokens", 4096)
    config.setdefault("timeout_seconds", 120)
    return config


def load_prompt(profile: dict, profile_path: Path) -> str:
    prompt_path = resolve_profile_path(profile_path, profile["prompt_path"])
    if not prompt_path.exists():
        raise SystemExit(f"Missing prompt file: {prompt_path}")
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
    raise SystemExit("Missing API key. Set config.api_key or export config.api_key_env.")


def endpoint_url(config: dict) -> str:
    base_url = str(config.get("base_url") or "").rstrip("/")
    endpoint = str(config.get("endpoint") or "/chat/completions")
    if not base_url:
        raise SystemExit("Missing config.base_url")
    if endpoint.startswith(("http://", "https://")):
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
    req = urllib.request.Request(
        endpoint_url(config),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
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
        raise RuntimeError(f"Summary API error {exc.code}: {body[:1000]}") from exc
    choices = result.get("choices") or []
    if choices:
        content = (choices[0].get("message") or {}).get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    text = result.get("output_text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    raise RuntimeError("Summary API returned no text.")


def compact_text(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2].rstrip()
    tail = text[-max_chars // 2 :].lstrip()
    return f"{head}\n\n[中间原文过长，已截断]\n\n{tail}"


def infer_title(path: Path, explicit: str | None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    return path.stem.strip() or "untitled"


def slugify(value: str, fallback: str = "review-note") -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value, flags=re.UNICODE).strip("-._")
    return (value[:90] or fallback).strip("-._")


def yaml_scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def render_frontmatter(meta: dict) -> str:
    lines = ["---"]
    for key, value in meta.items():
        lines.append(f"{key}: {yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def strip_code_fence(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(r"```(?:markdown|md)?\s*\n([\s\S]*?)\n```", stripped)
    return match.group(1).strip() if match else stripped


def validate_body(body: str, required_sections: list[str], title: str) -> None:
    for heading in required_sections:
        if heading not in body:
            raise RuntimeError(f"{title}: model output missing {heading}")
    if body.lstrip().startswith("---"):
        raise RuntimeError(f"{title}: model output should not include YAML frontmatter")
    match = re.search(r"^## 摘要\s*$([\s\S]*?)(?=^##\s+|\Z)", body, re.M)
    if not match:
        raise RuntimeError(f"{title}: missing summary section")
    summary = "".join(match.group(1).split())
    if len(summary) > 50:
        raise RuntimeError(f"{title}: summary is {len(summary)} chars; must be <= 50")


def default_output_path(wiki_root: Path, title: str) -> Path:
    return wiki_root / "raw" / "review" / "current" / f"{slugify(title)}.md"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wiki-root", type=Path, default=Path("Wiki Library"))
    parser.add_argument("--profiles-root", type=Path, default=DEFAULT_PROFILES_ROOT)
    parser.add_argument("--profile", required=True, help="Summary profile id, e.g. wechat-article or general-article.")
    parser.add_argument("--input", required=True, type=Path, help="Local original material file.")
    parser.add_argument("--output", type=Path, help="Review note output path. Defaults to raw/review/current/<title>.md.")
    parser.add_argument("--title", help="Review note title override.")
    parser.add_argument("--source-url", help="Original source URL.")
    parser.add_argument("--max-source-chars", type=int, default=60000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    wiki_root = resolve_wiki_root(args.wiki_root)
    profiles_root = args.profiles_root if args.profiles_root.is_absolute() else Path.cwd() / args.profiles_root
    if not profiles_root.exists():
        raise SystemExit(f"Profiles root not found: {profiles_root}")
    source_path = args.input if args.input.is_absolute() else Path.cwd() / args.input
    if not source_path.exists():
        raise SystemExit(f"Missing input file: {source_path}")
    profile, profile_path = load_profile(profiles_root, args.profile)
    config = load_model_config(profile, profile_path)
    system_prompt = load_prompt(profile, profile_path)
    source_text = source_path.read_text(encoding="utf-8", errors="replace")
    title = infer_title(source_path, args.title)
    output_path = args.output or default_output_path(wiki_root, title)
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path

    rel_original = os.path.relpath(source_path, start=wiki_root)
    user_prompt = (
        "请根据下面的本地原始材料生成候选 review 摘要。\n\n"
        f"profile: {args.profile}\n"
        f"title: {title}\n"
        f"source_url: {args.source_url or ''}\n"
        f"original_path: {rel_original}\n\n"
        "原文：\n"
        f"{compact_text(source_text, args.max_source_chars)}\n"
    )
    body = strip_code_fence(chat_completion(config, [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]))
    validate_body(body, profile.get("required_sections") or ["## 摘要", "## 详细内容", "## 注意事项"], title)

    meta = {
        "source_url": args.source_url,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "content_type": args.profile,
        "original_title": title,
        "category": None,
        "subcategory": None,
        "pulled_at": None,
        "duration": None,
        "likes": None,
        "comments": None,
        "favorites": None,
        "shares": None,
        "tags": [],
        "original": rel_original,
    }
    note = render_frontmatter(meta) + "\n\n" + body.rstrip() + "\n"
    print(f"Review note target: {output_path}")
    if args.dry_run:
        return 0
    if output_path.exists():
        raise SystemExit(f"Output already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(note, encoding="utf-8")
    print("Review note written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
