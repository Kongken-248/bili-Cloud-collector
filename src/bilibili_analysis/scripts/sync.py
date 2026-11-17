"""云端与本地数据合并脚本。

模块一实现：拉取云端数据并合并——同主键保留更新时间晚者；
弹幕/评论正文仅以本地为准；合并结果写 batch_log。
本阶段为空壳，仅定义命令行入口。

用法：
    python -m bilibili_analysis.scripts.sync --help
"""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。"""
    return argparse.ArgumentParser(description="云端快照与本地数据合并")


def main(argv: list[str] | None = None) -> int:
    """命令行入口：解析参数后执行合并（本阶段仅打印说明）。"""
    build_parser().parse_args(argv)
    print("[骨架] sync 合并逻辑将在模块一实现，当前无可执行任务。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
