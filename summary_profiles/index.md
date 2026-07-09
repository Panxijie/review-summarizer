# Summary Profiles Index

这个目录用于管理 `review-summarizer` 中“不同材料类型如何调用总结模型”的配置、提示词和输出约定。

调用总结模型前，先根据本索引选择 profile；不要临时混用其他材料类型的 prompt。

## 默认流程

1. 判断材料类型。
2. 在下表选择 profile。
3. 读取对应 `profile` JSON。
4. 使用 `profile.prompt_path` 指向的提示词。
5. 使用 `profile.model_config_path` 指向的模型配置模板；实际 API key 从环境变量或调用端安全配置读取，不写入仓库或 skill 文件。
6. 原文、转写稿、网页剪藏、媒体素材和拉取记录等统一放入 `raw/originals/`。
7. 模型生成的候选摘要放入 `raw/review/current/`。

## Profiles

| Profile | 适用材料 | Prompt | Config | 输出位置 | 原件位置 |
| --- | --- | --- | --- | --- | --- |
| `wechat-article` | 微信公众号、网页长文、手动剪藏文章 | `prompts/wechat-article.md` | `profiles/wechat-article.json` | `raw/review/current/` | `raw/originals/wechat/<date>/` |
| `douyin-video` | 抖音收藏视频、图文笔记、短视频转写 | `prompts/douyin-video.md` | `profiles/douyin-video.json` | `raw/review/current/<category>/` | `raw/originals/douyin/assets/`, `raw/originals/douyin/pulls/` |
| `general-article` | 普通网页文章、博客、newsletter | `prompts/general-article.md` | `profiles/general-article.json` | `raw/review/current/` | `raw/originals/web/<date>/` |

## 选择规则

- 有明确平台专用 profile 时，优先使用平台专用 profile。
- 没有专用 profile 但属于长文阅读材料时，用 `general-article`。
- 视频、音频、图文笔记等来自抖音收藏时，先用 `dy-faves-puller` 拉取本地原始材料和 manifest，再用 `review-summarizer` 按 `douyin-video` profile 生成候选总结；素材与 registry 规则仍以 `dy-faves-puller` 为准。
- 如果材料只是待收藏、不需要 AI 摘要，可直接进入 `raw/favorites/`，不调用总结模型。

## 安全约定

- 不在本目录保存真实 API key。
- 不在 log 或终端输出中打印 API 请求体、响应体、密钥、cookie 或 signed URL。
- 如果模型调用会把本地原文、转写稿或私密材料发到外部 API，应确认用户已经允许该材料被发送。
