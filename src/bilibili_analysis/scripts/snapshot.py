"""快照采集脚本。

模块一实现：对库内全部 bvid（head + control）重采统计字段写 snapshots 表，
首轮即写 T0；云端定时（GitHub Actions + cron-job.org）也复用同一入口。
本阶段为空壳，仅定义命令行入口。

用法：
    python -m bilibili_analysis.scripts.snapshot --help
"""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="B站视频统计字段快照采集")
    parser.add_argument("--date", type=str, default=None, help="测试：指定快照日期（YYYY-MM-DD）")
    return parser


def main(argv: list[str] | None = None) -> int:
    """命令行入口：解析参数后执行采集（本阶段仅打印说明）。"""
    build_parser().parse_args(argv)
    print("[骨架] snapshot 采集逻辑将在模块一实现，当前无可执行任务。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
