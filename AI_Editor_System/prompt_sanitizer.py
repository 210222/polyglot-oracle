# -*- coding: utf-8 -*-
"""
prompt_sanitizer.py - 提示词清洗器 (单一职责)
[来源]: 从 logic.py 拆分 sanitize_syntax / sanitize_negative_prompts
[职责]: 专职处理提示词字符串的清洗、去噪、参数合并，
        不包含任何 JSON 解析或 RAG 逻辑。

修复 (BN-05):
    原 sanitize_syntax 参数去重时，同 key 后值覆盖前值，
    但保留哪个取决于正则扫描顺序，存在静默歧义。
    本模块明确语义：last-win（后出现的参数优先），并在冲突时记录 warning。
"""
import re
import logging
from typing import Optional

logger = logging.getLogger("prompt_sanitizer")

# 需要从 T2I 提示词中清除的占位符列表
_PLACEHOLDERS = [
    r'\[State\]', r'\[Env\]', r'\[Lighting\]', r'\[Style\]',
    r'\[URL\]', r'\[W\]', r'\[Subject\]', r'\[Camera\]'
]

# Midjourney 参数正则（匹配 --key 或 --key value）
_MJ_PARAM_PATTERN = re.compile(r'(--[a-zA-Z]+)(?:\s+([a-zA-Z0-9:.]+))?')
_MJ_STRIP_PATTERN = re.compile(r'--[a-zA-Z]+(?:\s+[a-zA-Z0-9:.]+)?\s*')

# I2V 视频提示词中混入的 MJ 参数（需要完全清除）
_MJ_IN_I2V_PATTERN = re.compile(r'--[a-zA-Z]+\s+[\w:.]+')


def sanitize_t2i_prompt(prompt: str) -> str:
    """
    清理 T2I（文生图）提示词：
    1. 移除未填充的占位符（如 [State], [Env]）
    2. 提取并去重 Midjourney 参数（--v, --ar 等），last-win 语义
    3. 合并多余空格与尾部逗号

    Args:
        prompt: 原始 T2I 提示词字符串

    Returns:
        清洗后的提示词字符串
    """
    if not isinstance(prompt, str):
        return ""

    # 1. 清除占位符
    for p in _PLACEHOLDERS:
        prompt = re.sub(p, '', prompt, flags=re.IGNORECASE)

    # 2. 提取所有 MJ 参数，last-win 去重
    params_found = _MJ_PARAM_PATTERN.findall(prompt)
    clean_text = _MJ_STRIP_PATTERN.sub('', prompt).strip()

    param_dict: dict[str, str] = {}
    for key, val in params_found:
        if key in param_dict and param_dict[key] != val:
            logger.warning(
                f"⚠️ T2I 参数冲突: '{key}' 出现多次 "
                f"(原值: '{param_dict[key]}' → 新值: '{val}')，采用 last-win。"
            )
        param_dict[key] = val if val else ""

    final_params = " ".join(
        f"{k} {v}".strip() for k, v in param_dict.items()
    )

    # 3. 清理多余逗号与空格
    clean_text = re.sub(r',\s*,', ',', clean_text)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip(', ')

    return f"{clean_text} {final_params}".strip()


def sanitize_i2v_prompt(prompt: str) -> str:
    """
    清理 I2V（图生视频）提示词：
    剔除混入的 Midjourney 参数语法（--v, --ar 等），
    这些参数对视频引擎无效且可能干扰生成质量。

    Args:
        prompt: 原始 I2V 提示词字符串

    Returns:
        清洗后的提示词字符串
    """
    if not isinstance(prompt, str):
        return ""
    prompt = _MJ_IN_I2V_PATTERN.sub('', prompt)
    prompt = re.sub(r'\s+', ' ', prompt).strip()
    return prompt
