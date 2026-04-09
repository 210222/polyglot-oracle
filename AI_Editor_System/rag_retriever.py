# -*- coding: utf-8 -*-
"""
rag_retriever.py — RAG 查询层
v11 重构时遗漏的查询侧实现，补全 ingest → query 闭环。

设计原则：
- 与 ingest_engine/components/chroma_adapter.py 使用完全相同的 Embedding 模型
  (BAAI/bge-small-zh-v1.5 / BAAI/bge-small-en-v1.5)，保证向量空间一致。
- 懒加载：首次调用时加载模型，lru_cache 确保整个进程只加载一次。
- 静默降级：任何异常返回 ""，由 build_oracle_prompt 使用 FALLBACK_KNOWLEDGE 兜底。
"""
import logging
from functools import lru_cache

logger = logging.getLogger("rag_retriever")

# 按语言分组的集合名（与 ingest_engine ChromaRepository 命名规则一致）
_COLLECTIONS_ZH = ["director_expert_zh", "screenplay_expert_zh", "axiom_rules_zh", "shared_common_zh"]
_COLLECTIONS_EN = ["director_expert_en", "screenplay_expert_en", "axiom_rules_en", "shared_common_en"]


@lru_cache(maxsize=2)
def _get_embed_fn(lang: str):
    """
    延迟加载 SentenceTransformer Embedding 函数。
    lru_cache 保证每种语言只初始化一次，避免重复加载模型权重。
    """
    from chromadb.utils import embedding_functions
    model_name = "BAAI/bge-small-zh-v1.5" if lang == "zh" else "BAAI/bge-small-en-v1.5"
    logger.info(f"RAG: 加载 Embedding 模型 [{model_name}]")
    return embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model_name)


def _detect_lang(text: str) -> str:
    """按中文字符占比判断语言：> 20% 判定为中文，否则为英文。"""
    zh_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    return "zh" if zh_count / max(len(text), 1) > 0.2 else "en"


def query_rag(text: str, top_k: int = 3) -> str:
    """
    主查询接口：对输入文本进行语义检索，返回结构化 RAG context 字符串。
    失败时静默返回 ""，由 build_oracle_prompt 使用 FALLBACK_KNOWLEDGE 兜底。

    Args:
        text:  用户剧本文本（中文或英文，自动检测）
        top_k: 每个集合返回的最大命中数，默认 3

    Returns:
        格式化的 RAG 上下文字符串，或 "" (降级)
    """
    try:
        import chromadb
        from config import DB_PATH

        lang = _detect_lang(text)
        ef = _get_embed_fn(lang)
        col_names = _COLLECTIONS_ZH if lang == "zh" else _COLLECTIONS_EN

        client = chromadb.PersistentClient(path=DB_PATH)

        raw_docs = []
        for col_name in col_names:
            try:
                col = client.get_collection(name=col_name, embedding_function=ef)
                count = col.count()
                if count == 0:
                    continue
                results = col.query(
                    query_texts=[text],
                    n_results=min(top_k, count),
                    include=["documents", "metadatas", "distances"],
                )
                for doc, meta, dist in zip(
                    results["documents"][0],
                    results["metadatas"][0],
                    results["distances"][0],
                ):
                    raw_docs.append({"content": doc, "metadata": meta, "distance": dist})
            except Exception as e:
                logger.warning(f"RAG: 查询集合 [{col_name}] 失败: {e}")

        if not raw_docs:
            logger.warning("RAG: 无检索结果，降级使用 FALLBACK_KNOWLEDGE")
            return ""

        # 按距离升序（余弦距离越小 = 语义越相关）
        raw_docs.sort(key=lambda x: x["distance"])

        # 距离阈值过滤：余弦距离 > MAX_DISTANCE 的结果相关性太低，直接丢弃
        MAX_DISTANCE = 0.6
        before = len(raw_docs)
        raw_docs = [d for d in raw_docs if d["distance"] <= MAX_DISTANCE]
        filtered = before - len(raw_docs)
        if filtered:
            logger.info(f"RAG: 距离过滤丢弃 {filtered} 条低相关结果（阈值={MAX_DISTANCE}）")
        if not raw_docs:
            logger.warning("RAG: 过滤后无有效结果，降级使用 FALLBACK_KNOWLEDGE")
            return ""

        # 按 kb_category 分桶，与 v10 IntelligentRAGLayer 语义对齐
        buckets: dict = {"RULES": [], "EXPERT": [], "CONTEXT": []}
        for item in raw_docs:
            cat = item["metadata"].get("kb_category", "")
            content = item["content"].strip()
            if "axiom" in cat:
                buckets["RULES"].append(f"- [AXIOM] {content}")
            elif cat in ("director_expert", "screenplay_expert"):
                buckets["EXPERT"].append(f"- [EXPERT] {content}")
            else:
                buckets["CONTEXT"].append(f"- {content}")

        blocks = []
        if buckets["RULES"]:
            blocks.append(
                "<SECTION: WORLD_RULES (HIGHEST PRIORITY — OVERRIDE USER SCRIPT)>\n"
                + "\n".join(buckets["RULES"])
            )
        if buckets["EXPERT"]:
            blocks.append(
                "<SECTION: EXPERT_KNOWLEDGE (VISUAL GUIDANCE)>\n"
                + "\n".join(buckets["EXPERT"])
            )
        if buckets["CONTEXT"]:
            blocks.append(
                "<SECTION: REFERENCES (CONTEXT)>\n"
                + "\n".join(buckets["CONTEXT"])
            )

        context = "\n\n".join(blocks)
        logger.info(
            f"RAG: 检索完成 — 语言={lang}, 总命中={len(raw_docs)}, "
            f"RULES={len(buckets['RULES'])}, EXPERT={len(buckets['EXPERT'])}, "
            f"CONTEXT={len(buckets['CONTEXT'])}"
        )
        return context

    except Exception as e:
        logger.warning(f"RAG: query_rag 整体异常，使用 FALLBACK_KNOWLEDGE: {e}")
        return ""
