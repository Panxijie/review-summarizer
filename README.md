# Review Summarizer

一个 Codex skill，用于把已经保存在本地的原始材料整理成可人工复核的 Markdown 候选笔记，服务于 Wiki Library 工作流。

这个 skill 从 `raw/originals/` 下已有的文件开始处理，并把候选笔记写入 `raw/review/current/`。它不会抓取网页、登录平台、下载媒体，也不会把候选笔记提升到最终 wiki。

## 包含内容

- 面向微信公众号文章、普通网页文章和抖音视频的材料 profile。
- Prompt 模板和 OpenAI-compatible 模型配置模板。
- 用于文章总结、抖音转写稿总结、可重试 manifest 更新、并行总结监督和候选笔记整理的脚本。
- 用于避免 API key、cookie、signed URL、源文本和模型响应进入日志或提交文件的安全约束。

## 仓库结构

- `SKILL.md`：Codex skill 指令和工作流规则。
- `summary_profiles/`：profile 元数据、prompts 和模型配置模板。
- `scripts/`：总结、整理、元数据和 manifest 辅助脚本。
- `agents/openai.yaml`：Codex skill 的展示元数据。

## 安装

将此仓库克隆或复制到你的 Codex skills 目录，例如：

```bash
~/.codex/skills/review-summarizer
```

通过环境变量配置 API 访问。默认模型配置会从 `DEEPSEEK_API_KEY` 读取密钥；不要把真实密钥提交到此仓库。

在 macOS 的 Codex Desktop 中，GUI app 可能不会继承 shell 里的 `export`。可以用下面的命令把密钥设置到当前登录会话：

```zsh
launchctl setenv DEEPSEEK_API_KEY 'your-key-here'
```

然后完全退出并重新打开 Codex。

## 用法

处理本地文章：

```bash
python3 scripts/summarize_article_to_review.py \
  --wiki-root "Wiki Library" \
  --profile general-article \
  --input "Wiki Library/raw/originals/web/YYYY-MM-DD/article.md"
```

处理由 `dy-faves-puller` 创建的抖音 pull manifest：

```bash
python3 scripts/summarize_notes_with_model.py \
  --manifest "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/run_manifest.json"
```

在正式整理前先预览：

```bash
python3 scripts/organize_content_library.py \
  --output "Wiki Library/raw/originals/douyin" \
  --manifest "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/run_manifest.json" \
  --pulled-at "YYYY-MM-DD HH:MM"
```

## 安全说明

此仓库只应该包含可复用的代码、prompts 和模板。请将本地原始材料、转写稿、媒体文件、日志、`.env` 文件、cookie、signed URL 和模型服务商密钥保留在 Git 之外。

仓库内置的 `.gitignore` 已排除常见本地密钥文件、本地模型配置、日志、缓存和构建输出。如果你创建包含真实凭据的服务商专用配置，请使用 `*.local.json`、`*-local.json` 或其他已忽略的私有路径。

## 许可证

MIT
