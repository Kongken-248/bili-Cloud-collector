"""大模型调用层。

模块四实现。OpenAI 兼容 HTTP API：
- 统一入口 chat(prompt, temperature=0.3) -> LLMResult；
- 超时 / 重试 / 降级三处防御，失败返回结构化结果不抛异常；
- batch_chat() 串行 + 进度回调；
- 每次调用记录到 data/llm_calls.csv。

本阶段（模块 0）为空壳，仅保留模块边界说明。
"""
