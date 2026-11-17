# B站视频数据分析与可视化系统（毕业设计）

研究型毕业设计系统：通过爬虫采集 B站公开数据，完成清洗入库、统计分析、
可视化与「大模型自动生成分析结论」的完整链路。

> 当前进度：项目骨架（模块 0）。详细的安装 / 运行 / 采集命令、配置说明、
> AI 功能说明与常见问题将在模块五（系统整合）补全。

## 安装（第一步）

```bash
pip install -e .
```

采用 src 布局，`pip install -e .` 后可编辑安装，`import bilibili_analysis`
指向 `src/`，脚本统一用模块方式运行：

```bash
python -m bilibili_analysis.scripts.crawler --help
```

## 目录结构

见 `pyproject.toml` 与 `docs/数据字典.md`。

## 数据与字段口径

表结构与字段定义唯一真源：`docs/数据字典.md`。
