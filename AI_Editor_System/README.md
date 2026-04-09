# Polyglot Oracle — AI 跨平台视频生成编排系统

> 将线性剧本自动编译为多引擎合规的视频生成提示词，覆盖 Kling 2.6、即梦 AI、Hailuo Video-01、Luma Ray 3、Google Veo 3.1。

---

## 项目概述

Polyglot Oracle 是一套面向 AI 视频生产流程的**提示词工程与编排系统**。核心问题是：不同视频生成引擎（Kling、Hailuo、Luma、Veo 等）对提示词的语法、词序、时间戳格式要求完全不同，人工适配效率极低且容易出错。

本系统通过**五阶段 Pipeline + 动态引擎适配器**，将一段自然语言剧本自动转化为符合目标引擎语法规范的生产级提示词，同时维护跨镜头角色视觉连续性（Visual Ledger）。

---

## 核心功能

### 1. 多引擎动态适配（Polyglot Adapter）
- 支持 5 个主流视频生成引擎，每个引擎有独立的语法规则（词序、时间戳、运镜指令格式）
- 代码层 Adapter 在 LLM 输出后执行后处理校验，确保引擎合规性
- 引擎切换零成本：UI 下拉选择，Pipeline 自动重新编译

### 2. 神经电影级提示词注入（Neural Cinema Formula）
- **Phase 0 潜意识摩擦扫描**：自动检测 6 类视频生成失效向量（运动惯性失效、光照拓扑失效、材质表面响应失效、主体环境脱节、深度层次失效、声画同步失效）
- **物理锚点注入**：强制注入力学动词、光照拓扑描述符、材质微纹理响应
- **焦段情绪映射**：14-135mm 焦段与情绪寄存器的系统性映射规则

### 3. RAG 知识库增强
- ChromaDB 向量数据库，双语集合（中/英），BGE-small 嵌入模型
- 余弦距离阈值过滤（0.6），确保注入上下文的相关性
- 知识库涵盖：导演技法、剧本写作、视觉叙事规范

### 4. Visual Ledger 跨镜头连续性追踪
- 持久化 JSON 状态机，追踪角色物理状态（受伤、污损、换装）
- LLM 自动检测剧本中的状态变化事件并更新 Ledger
- 跨 session 持久化，重启后自动恢复

### 5. 自修复 JSON 解析（Self-Repair Pipeline）
- 故障分型：TRUNCATED / WRAPPED / EMPTY_ASSETS / CORRUPT
- 对症注入 repair_hint，CORRUPT 类型直接失败不浪费 token
- 最多 3 次重试，schema 错误在第 2 次直接终止

### 6. UE5 UDP 实时推送
- 生成完成后自动向 Unreal Engine 5 发送 UDP 数据包
- 支持生产端（11111）和调试端（11112）双端口

---

## 技术架构

```
用户剧本输入
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  ai_editor_core_v2.py — 五阶段 Pipeline              │
│                                                     │
│  Phase 1: resolve_engine()  引擎名称解析             │
│  Phase 2: build_oracle_prompt()  Prompt 组装         │
│           ├── SYSTEM_PROMPT_V11_0 (config.py)       │
│           ├── Visual Ledger (JSON 状态)              │
│           ├── ENGINE RULES (_format_engine_rules)   │
│           └── RAG Context (rag_retriever.py)        │
│  Phase 3: _llm_with_repair()  LLM 调用+自修复        │
│  Phase 4: extract_and_validate_assets()  JSON 解析  │
│  Phase 5: postprocess_assets()  后处理+状态同步      │
│           └── apply_engine_adapter()  引擎适配       │
└─────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────┐    ┌──────────────┐    ┌────────────┐
│  web_ui.py   │    │ ue_bridge.py │    │ data/      │
│  Streamlit   │    │  UDP → UE5   │    │ ledger.json│
└──────────────┘    └──────────────┘    └────────────┘
```

---

## 技术栈

| 层级 | 技术 |
|------|------|
| LLM 接入 | OpenAI-compatible API（Coze / 智谱 GLM / OpenAI） |
| 向量数据库 | ChromaDB PersistentClient |
| 嵌入模型 | BAAI/bge-small-en-v1.5 / bge-small-zh-v1.5 |
| Web UI | Streamlit |
| 图像理解 | 智谱 GLM-4V Flash（云端 API，替代本地 Qwen2-VL） |
| 实时通信 | UDP Socket → Unreal Engine 5 |
| 运行环境 | Python 3.10+，Windows / Linux |

---

## 系统设计亮点

### Prompt Engineering 架构
- 系统提示词（~3000 tokens）与引擎规则（按需注入，~200 tokens）分离
- 例句从静态 System Prompt 抽出，改为运行时按目标引擎动态注入，节省 ~400 tokens/次
- Token 预算守卫：中英混合精确估算（`cn_chars×2 + others÷4`），阈值 8000 tokens

### 工程健壮性
- Mock Provider 污染哨兵：`MOCK_SCENE_001` 检测，防止假成功静默通过
- LLM 异常直接穿透（不再静默降级），错误在 UI 层可见
- 超时路径 `raise TimeoutError` 替代原 Mock fallback

### 数据管道
- ingest_engine 与 rag_retriever 通过 `.env` 统一 `CHROMA_DB_PATH`，消除数据孤岛
- 脏数据定向清理工具（`clean_dirty_records.py`）

---

## 快速启动

```bash
# 1. 克隆仓库
git clone https://github.com/210222/polyglot-oracle.git
cd polyglot-oracle/AI_Editor_System

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 用编辑器打开 .env，填写 COZE_API_KEY 或 OPENAI_API_KEY

# 4. 初始化知识库（首次运行，可选）
# 将参考资料 PDF 放入 sample_docs/ 目录，然后运行：
python run_ingest.py
# 跳过此步骤系统仍可运行，RAG 将使用内置 Fallback 知识库

# 5. 启动 Web UI
streamlit run web_ui.py
```

---

## 目录结构

```
AI_Editor_System/
├── ai_editor_core_v2.py   # 核心 Pipeline（五阶段编排）
├── config.py              # 系统提示词 + 引擎配置
├── web_ui.py              # Streamlit 主界面
├── ui_components.py       # UI 组件（Ledger / 资产卡片）
├── services_v2.py         # LLM Gateway（多 Provider）
├── rag_retriever.py       # RAG 检索（距离阈值过滤）
├── json_extractor.py      # LLM 输出 JSON 解析器
├── logic_v2.py            # 工具函数门面层
├── ue_bridge.py           # UE5 UDP 推送
├── ingest_engine/         # 知识库入库 Pipeline
│   ├── stages/            # Stage1(PDF) Stage2(VLM) Stage3(Embed)
│   └── config/settings.py
└── data/
    ├── vector_store/      # ChromaDB 持久化目录
    └── ledger.json        # Visual Ledger 持久化
```
