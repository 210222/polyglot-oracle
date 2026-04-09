# -*- coding: utf-8 -*-
"""
logic_v2.py - 重构后的统一入口层
[架构]: 本文件是三个单一职责模块的门面 (Facade)，
        调用方只需 from logic_v2 import ... 即可，无需关心内部拆分细节。
        原 logic.py 保持不变，两者可并存，迁移时逐步替换导入即可。

模块映射:
    smart_json_extractor  → json_extractor.extract_json        (BN-01 已修复)
    sanitize_syntax       → prompt_sanitizer.sanitize_t2i_prompt (BN-05 已修复)
    sanitize_negative_*   → prompt_sanitizer.sanitize_i2v_prompt
    IntelligentRAGLayer   → rag_formatter.format_rag_context    (BN-02/03 已修复)
    perform_translation   → 已删除（幽灵函数，无实际实现）
"""

from json_extractor import extract_json as smart_json_extractor
from prompt_sanitizer import sanitize_t2i_prompt as sanitize_syntax
from prompt_sanitizer import sanitize_i2v_prompt as sanitize_negative_prompts
from rag_formatter import format_rag_context, reorder_primacy_recency

# 向下兼容：保留 IntelligentRAGLayer 类名入口
class IntelligentRAGLayer:
    """向下兼容包装器，内部委托给 rag_formatter.format_rag_context。"""
    @staticmethod
    def format_context(raw_docs: list) -> str:
        return format_rag_context(raw_docs)


__all__ = [
    "smart_json_extractor",
    "sanitize_syntax",
    "sanitize_negative_prompts",
    "IntelligentRAGLayer",
    "format_rag_context",
    "reorder_primacy_recency",
]
