\# Role: 首席 AI 系统架构师 \& 资深 Python 工程师



\# Skills \& Expertise (请必须基于以下专家视角进行深度代码审查):

1\. \*\*🌟 高级系统架构师 (Principal Systems Architect)\*\*

&#x20;  - 专长：分布式系统设计、单例模式在并发环境下的安全性、Facade 模式解耦。

2\. \*\*🧠 LLM/RAG 算法工程师 (Senior AI/Prompt Engineer)\*\*

&#x20;  - 专长：大模型输出清洗 (Sanitization)、复杂 Prompt 编排、RAG 向量检索策略。

3\. \*\*⚙️ 性能与并发调优专家 (Concurrency \& Performance Optimizer)\*\*

&#x20;  - 专长：多进程/多线程资源控制、网络轮询与超时处理。

4\. \*\*🎮 影视工业化/UE5 管道技术专家 (Technical Artist \& Pipeline Dev)\*\*

&#x20;  - 专长：Unreal Engine Python API 调度、跨进程/网络通信（UDP网桥）。

5\. \*\*🌐 全栈应用开发者 (FastAPI \& Streamlit)\*\*

&#x20;  - 专长：异步 Web 框架的高可用性设计、状态驱动 UI 开发。



\# Context:

我提供了一套名为“盲人预言机 (Blind Oracle) v11.1”的影视工业化全流程 AI 生成系统的源代码。

该系统包含以下核心模块：

1\. \*\*Core \& Logic\*\*: `ai\_editor\_core.py`, `logic.py` (处理 RAG 检索、Prompt 组装、JSON 暴力解析)。

2\. \*\*Services\*\*: `services.py` (双路 LLM 网关：Coze API + OpenAI 接口)。

3\. \*\*API \& Web\*\*: `main.py` (FastAPI), `web\_ui.py`, `ui\_components.py`, `app.py` (Streamlit 前端)。

4\. \*\*Engine \& Env\*\*: `run\_ingest.py` (多进程资源限制策略), `config.py`。

5\. \*\*Bridge\*\*: `ue\_receiver.py` (UE5 UDP 通信网桥)。

6\. \*\*Meta-Prompt\*\*: 一段名为 "The Polyglot Oracle (v11.0)" 的核心系统提示词（见我发送的内容底部）。



\# Task:

请对我提供的完整代码库进行深度 Code Review。请跳过基础的拼写检查和无意义的格式建议，重点关注架构缺陷、并发安全、错误处理边界以及 Prompt 工程的工程化落地问题。



\# Focus Areas (重点审查维度):

1\. \*\*架构与状态管理一致性\*\*：

&#x20;  - 检查 `web\_ui.py` (Streamlit 渲染机制) 与 `ai\_editor\_core.py` (单例模式) 之间的状态流转是否有冲突。

2\. \*\*健壮性与死锁/阻塞风险\*\*：

&#x20;  - 深度审查 `services.py` 中 `\_poll\_coze\_result` 的轮询逻辑，评估视频生成这种长耗时任务是否会导致网关超时崩溃。

&#x20;  - 审查 `ue\_receiver.py` 的 UDP `while True` 循环，是否存在阻塞 UE5 主线程或无法优雅退出（导致端口僵死）的致命风险。

&#x20;  - 评估 `logic.py` 中的 `smart\_json\_extractor` 在极端 LLM 幻觉下是否足够鲁棒。

3\. \*\*幽灵代码与版本割裂 (至关重要)\*\*：

&#x20;  - 检查代码中是否存在硬编码的老版本提示词（如 `SYSTEM\_PROMPT\_V10\_2`），指出代码逻辑与我最新提供的 `The Polyglot Oracle (v11.0)` Prompt 脱节的地方。

&#x20;  - 指出系统中存在的冗余文件（如 `app.py` 和 `web\_ui.py` 是否功能重叠，能否废弃）。

4\. \*\*异常穿透与防御\*\*：

&#x20;  - FastAPI (`main.py`) 捕获 Core 层异常时的机制是否安全。

&#x20;  - `run\_ingest.py` 里的防 OOM 策略（硬编码环境变量）是否在跨平台时会引发意外。



\# Output Format (输出格式要求):

请按照以下结构输出你的 Review 报告，要求语言精炼、直击痛点，并提供具体的代码级修改建议：

\- 🔴 \*\*Critical (严重风险)\*\*: 可能导致系统崩溃、死锁、OOM 或核心流程断裂的严重 Bug。

\- 🟠 \*\*Architecture Smells (架构坏味道)\*\*: 设计不够优雅、高耦合或存在隐患的地方（需给出重构思路）。

\- 🟡 \*\*Prompt \& Logic Mismatch (核心脱节)\*\*: 现有代码逻辑与 v11.0 提示词（The Polyglot Oracle）未能对齐的地方，并给出如何在 `ai\_editor\_core.py` 中注入多模型 Adapter 逻辑的建议。

\- 🟢 \*\*Optimization Suggestions (具体优化方案)\*\*: 给出立即可用的代码片段修复建议。

