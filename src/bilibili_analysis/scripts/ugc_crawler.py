"""弹幕 / 评论本地采集脚本（登录态）。

模块一实现：弹幕按 cid 分段拉取至接口上限，评论按 aid 拉一级热评（主楼），
逐视频写 danmaku_fetch_log / comment_fetch_log 对账。
本阶段为空壳，仅定义命令行入口。

用法：
    python -m bilibili_analysis.scripts.ugc_crawler --help
"""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。"""
    return argparse.ArgumentParser(description="B站弹幕 / 评论本地采集（登录态）")


def main(argv: list[str] | None = None) -> int:
    """命令行入口：解析参数后执行采集（本阶段仅打印说明）。"""
    build_parser().parse_args(argv)
    print("[骨架] ugc_crawler 采集逻辑将在模块一实现，当前无可执行任务。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
