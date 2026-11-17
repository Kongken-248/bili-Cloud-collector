"""采集与清洗脚本子包。

脚本一律通过 `python -m bilibili_analysis.scripts.<name>` 运行，
不要用文件路径直接执行。

- crawler.py：榜单 / UP主 / 对照投稿采集。
- ugc_crawler.py：弹幕 / 评论本地采集（登录态）。
- snapshot.py：快照采集（云端定时也复用同一入口）。
- sync.py：云端与本地数据合并。
- clean.py：清洗入库。
"""
