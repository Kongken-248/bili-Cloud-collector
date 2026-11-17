# 云端快照工作流

本目录用于存放 GitHub Actions 快照工作流，在模块一（数据采集）补齐：

- 由 cron-job.org 触发，每天 2 轮运行 `snapshot.py`（复用同一采集入口）；
- 轻量数据（snapshots + 榜单/UP主元数据）git push 回仓库；
- 不采集、不存储弹幕/评论正文（存储上限），不接触 SESSDATA。

模块 0（项目骨架）阶段暂不创建 workflow 文件。
