# 官方原文 ingest 流程

## 目录
- `policy_official_ingest.json`：业务消费的官方原文配置，包含方向 ID、标题、授权机构、发布时间、参考链接、重点和观察 tag。
- `scripts/refresh_official_ingest.py`：校验/排序脚本，确保 `published_at` 为 ISO 日期、引用链接存在、key points/watch tags 去重、结果按时间降序写回。
- `scripts/check_official_updates.py`：扫描配置，报告任何缺 `published_at` / `reference_url` 的条目，便于补全。
- `scripts/publish_android_release.sh`：发布前自动调用 `refresh_official_ingest.py`，确保正式发行时 ingest 数据合法。

## 更新流程
1. 每次添加/修改官方条目后，先运行 `python3 scripts/check_official_updates.py`，看哪些条目缺信息。
2. 补全 `reference_url`/`published_at`，再运行 `python3 scripts/refresh_official_ingest.py` 让字段遵循格式。
3. 发布时（`bash scripts/publish_android_release.sh ...`）会自动走第 2 步，任何遗漏都会被格式化。
4. 为持续更新，可安排 `scripts/ci_official_ingest.sh` 在 CI/cron 中自动跑 `check → refresh`，再触发发布。

## 后续方向
- 可将脚本放到 cron/CI，定期同步 `reference_url` 内容并重新格式化。  
- 把 `check_official_updates.py` 输出集成到 PR 检查或 pre-commit hook，确保新进入的政策都带完整元数据。
