# -*- coding: utf-8 -*-
"""
rag_formatter.py - RAG 上下文格式化器 (单一职责)
[来源]: 从 logic.py 拆分 IntelligentRAGLayer + reorder_context_primacy_recency
[职责]: 专职将 ChromaDB 检索结果格式化为 LLM 可读的结构化上下文字符串，
        不包含任何 JSON 解析或提示词清洗逻辑。

修复 (BN-02): 用枚举 + 配置字典替换字符串硬匹配分桶规则。
修复 (BN-03): reorder 算法修正，真正实现首尾优先（primacy + recency）语义。
"""
import logging
from enum import Enum
from typing import List, Dict

logger = logging.getLogger("rag_formatter")


# ==============================================================================
# 分桶枚举与路由配置（替代 BN-02 的字符串硬匹配）
# ==============================================================================

class Bucket(str, Enum):
    WORLD_RULES = "WORLD_RULES"
    TECH_SPECS  = "TECH_SPECS"
    REFERENCES  = "REFERENCES"


# 路由规则配置：优先级从上到下，首个匹配即停止
# 修改分类规则只需编辑此处，不再散落在 if-elif 链中
_ROUTING_RULES: List[Dict] = [
    {
        "bucket": Bucket.WORLD_RULES,
        "match": lambda meta: (
            str(meta.get("is_vip", "False")).lower() == "true"
            or any(kw in meta.get("source", "").lower()
                   for kw in ("rule", "axiom", "law", "mandate"))
        ),
        "prefix": "[AXIOM]"
    },
    {
        "bucket": Bucket.TECH_SPECS,
        "match": lambda meta: (
            any(kw in meta.get("kb_category", "").lower()
                for kw in ("director", "spec", "technique", "visual"))
        ),
        "prefix": "[VISUAL]"
    },
    {
        # 默认桶：上面两条都不匹配时落入
        "bucket": Bucket.REFERENCES,
        "match": lambda meta: True,
        "prefix": ""
    },
]

# 每个桶在最终上下文中的显示上限（防止 context 过长）
_BUCKET_LIMITS: Dict[Bucket, int] = {
    Bucket.WORLD_RULES: 5,
    Bucket.TECH_SPECS:  5,
    Bucket.REFERENCES:  3,
}

# 对应 LLM Prompt 中的 Section 标题
_BUCKET_SECTION_NAMES: Dict[Bucket, str] = {
    Bucket.WORLD_RULES: "WORLD_RULES",
    Bucket.TECH_SPECS:  "VISUAL_SPECS",
    Bucket.REFERENCES:  "REFERENCES",
}


# ==============================================================================
# 首尾重排算法（修复 BN-03）
# ==============================================================================

def reorder_primacy_recency(docs: List[str]) -> List[str]:
    """
    Lost-in-the-Middle 修复：将最重要的文档放在列表首尾，
    次要文档放在中间（LLM 对中间位置内容的注意力最低）。

    正确语义（修复 BN-03 算法错误）:
        输入  [A, B, C, D, E]
        输出  [A, C, D, E, B]  ← A 最重要放首位，B 次重要放末位，其余填中间

    原 logic.py 实现将第 2 个元素（而非最后一个）放尾部，与注释语义不符。
    """
    if len(docs) < 3:
        return docs

    first = docs[0]           # 最高优先级 → 首位（primacy）
    last  = docs[1]           # 次高优先级 → 末位（recency）
    middle = docs[2:]         # 其余 → 中间

    return [first] + middle + [last]


# ==============================================================================
# 文档路由
# ==============================================================================

def _route_doc(meta: dict) -> tuple[Bucket, str]:
    """根据配置路由规则返回 (目标桶, 前缀标签)。"""
    for rule in _ROUTING_RULES:
        if rule["match"](meta):
            return rule["bucket"], rule["prefix"]
    # 永远不会到达（最后一条规则 match 恒为 True），保留防御
    return Bucket.REFERENCES, ""


# ==============================================================================
# 公开接口
# ==============================================================================

def format_rag_context(raw_docs: List[Dict]) -> str:
    """
    将 ChromaDB 检索结果格式化为结构化的 LLM 上下文字符串。

    Args:
        raw_docs: ChromaDB 返回的文档列表，每项格式：
                  {"content": str, "metadata": {"source": str, "kb_category": str, ...}}

    Returns:
        格式化后的上下文字符串，包含 <SECTION: xxx> 分区标签，
        或 "(No relevant knowledge found)" 若输入为空。
    """
    if not raw_docs:
        return "(No relevant knowledge found)"

    buckets: Dict[Bucket, List[str]] = {b: [] for b in Bucket}

    for doc in raw_docs:
        meta    = doc.get("metadata", {})
        content = doc.get("content", "").strip()
        source  = meta.get("source", "Unknown")
        lang    = meta.get("language", "zh").upper()

        citation   = f"[{source}] [{lang}] {content}"
        bucket, prefix = _route_doc(meta)
        entry = f"- {prefix} {citation}".strip() if prefix else f"- {citation}"
        buckets[bucket].append(entry)

    # 对 REFERENCES 和 TECH_SPECS 做首尾重排
    buckets[Bucket.REFERENCES] = reorder_primacy_recency(buckets[Bucket.REFERENCES])
    buckets[Bucket.TECH_SPECS] = reorder_primacy_recency(buckets[Bucket.TECH_SPECS])

    blocks = []
    for bucket in (Bucket.WORLD_RULES, Bucket.TECH_SPECS, Bucket.REFERENCES):
        items = buckets[bucket]
        if not items:
            continue
        limit        = _BUCKET_LIMITS[bucket]
        section_name = _BUCKET_SECTION_NAMES[bucket]
        body         = "\n".join(items[:limit])
        blocks.append(f"\n<SECTION: {section_name}>\n{body}")

    result = "\n".join(blocks)
    return result if result.strip() else "(No relevant knowledge found)"
