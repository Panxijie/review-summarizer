# Review Summarizer

一个 Codex skill，用于把已保存在本地的原始材料整理成可人工复核的 Markdown 候选笔记，服务于 Wiki Library 工作流。支持微信公众号文章、普通网页文章、newsletter，以及由 `dy-faves-puller` 拉取的抖音材料。

输入位于 `Wiki Library/raw/originals/`，候选笔记写入 `Wiki Library/raw/review/current/`。本 skill 不负责抓取网页、登录平台或下载媒体，也不把候选笔记提升到最终 wiki。抖音材料应先由 `dy-faves-puller` 生成本地素材和 pull manifest。

## 仓库结构

- `SKILL.md`：完整工作流、完成条件和分类规则。
- `summary_profiles/`：材料类型索引、prompt、profile 和模型配置模板。
- `scripts/summarize_article_to_review.py`：总结单篇本地文章。
- `scripts/run_douyin_review_pipeline.py`：监督抖音批次的总结、校验、整理和本地文件链接补全。
- `scripts/summarize_notes_with_model.py`、`scripts/run_parallel_douyin_summary.py`、`scripts/organize_content_library.py`：分步处理或定向修复抖音批次。
- `agents/openai.yaml`：Codex skill 的展示元数据。

## 安装与模型配置

将此仓库克隆或复制到 Codex skills 目录，例如 `~/.codex/skills/review-summarizer`。运行命令前，先在 `summary_profiles/index.md` 选择材料类型，并检查对应 profile 和模型配置。当前三个 profile 共用默认配置 `summary_profiles/model_configs/openai-compatible-default.json`，模型 ID 为 `deepseek-flash`（DeepSeek V4.1 Flash），通过 `DEEPSEEK_API_KEY` 读取 API key；不要把真实密钥写入仓库。更改默认模型只影响后续模型调用，不会自动重写已生成的候选笔记。

在 macOS 的 Codex Desktop 中，GUI app 可能不会继承 shell 里的 `export`。可在 Terminal 为当前登录会话设置环境变量，然后完全退出并重新打开 Codex：

```zsh
launchctl setenv DEEPSEEK_API_KEY 'your-key-here'
```

模型调用会把选中的本地原文或转写稿发送到配置的外部 API。处理私有材料前，应确认已获准发送。

以下命令在包含 `Wiki Library` 的目录执行，先将 `SKILL_DIR` 设为此 skill 的实际安装路径：

```bash
SKILL_DIR="/absolute/path/to/review-summarizer"
```

## 处理本地文章

将文章先放入 `Wiki Library/raw/originals/`，然后运行：

```bash
python3 "$SKILL_DIR/scripts/summarize_article_to_review.py" \
  --wiki-root "Wiki Library" \
  --profile general-article \
  --input "Wiki Library/raw/originals/web/YYYY-MM-DD/article.md"
```

微信公众号文章使用 `--profile wechat-article`。可用 `--title`、`--source-url`、`--output` 指定笔记信息。脚本会校验必需章节，再写入 `raw/review/current/`。`--dry-run` 仍会调用模型并校验生成内容，只跳过写入。

## 处理抖音 pull

确认 pull manifest 已由 `dy-faves-puller` 生成，并确认可以将本批候选追加到 `raw/review/current/` 后，运行完整流水线：

```bash
python3 "$SKILL_DIR/scripts/run_douyin_review_pipeline.py" \
  --manifest "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/run_manifest.json" \
  --output-root "Wiki Library/raw/originals/douyin" \
  --pull-id "<pull-id>" \
  --detach
```

当 pull ID 不是以 `YYYY-MM-DD_HH-mm` 开头时，另加 `--pulled-at "YYYY-MM-DD HH:MM"`。`--detach` 会启动独立监督进程并返回 PID；流水线随后自动选择新的候选、重试未完成的总结、检查必需章节、预览并执行整理、补全本地文件链接，最后验证结果。它会跳过 `current` 中已有的相同 `aweme_id`，并允许把本批新候选追加到非空的 `current`。

该 pull 的 `json/` 目录会记录 `review-supervisor.log`，运行时有 `review-supervisor.pid`；执行对应阶段时还会生成 `summary-retry.log` 和 `organization-preview.txt`。以日志中的 `PIPELINE_COMPLETE` 和最终文件校验为自动流水线的完成依据；进程启动或仅有部分总结成功不代表批次完成。若完成条件失败，检查日志和 manifest，保留已完成记录后重启同一流水线继续处理。不要同时对同一 manifest 启动多个写入进程。

流水线完成后，逐条核对本批候选的标题、正文和分类；必要时调整 `category`、`subcategory` 与笔记所在目录。完整完成条件和现有分类规则见 [`SKILL.md`](SKILL.md)。

需要分步修复时，可使用 `summarize_notes_with_model.py` 的 `--indices` 只重试指定记录，再以同一组索引运行 `organize_content_library.py` 预览，确认完成条件后加 `--apply`。并行总结入口 `run_parallel_douyin_summary.py` 适用于经授权的批次；它的 `--require-model` 应与配置中的模型 ID 一致，当前为 `deepseek-flash`。使用要求见 `SKILL.md`。

## 安全说明

仓库只应包含可复用的代码、prompt 和模板。原始材料、转写稿、媒体、日志、`.env`、cookie、signed URL 和模型密钥应留在 Git 之外。`.gitignore` 已排除常见本地密钥文件、私有模型配置、日志、缓存和构建输出；若创建含真实凭据的配置，请使用被忽略的 `*.local.json` 或 `*-local.json` 路径。

## 许可证

MIT
