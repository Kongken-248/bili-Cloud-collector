"""清洗入库脚本。

模块二实现：读取 data/raw/ 原始 JSON，按清洗规则写入八张表并打印清洗前后统计对比。
注意：snapshots 表唯一写入入口是 snapshot.py，clean.py 不写它。
本阶段为空壳，仅定义命令行入口。

用法：
    python -m bilibili_analysis.scripts.clean --help
"""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。"""
    return argparse.ArgumentParser(description="B站原始数据清洗入库")


def main(argv: list[str] | None = None) -> int:
    """命令行入口：解析参数后执行清洗（本阶段仅打印说明）。"""
    build_parser().parse_args(argv)
    print("[骨架] clean 清洗逻辑将在模块二实现，当前无可执行任务。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
