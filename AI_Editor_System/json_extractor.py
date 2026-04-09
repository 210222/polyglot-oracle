# -*- coding: utf-8 -*-
"""
json_extractor.py - LLM 输出 JSON 解析器 (单一职责)
[来源]: 从 logic.py 拆分，根除贪婪正则 Bug (BN-01)
[职责]: 专职处理 LLM 原始输出 → 合法 Python dict 的转换，
        不包含任何业务逻辑（不知道 assets/RAG/Prompt 是什么）。

核心修复 (BN-01):
    原 logic.py 使用贪婪正则 r'\{[\s\S]*\}'，在 LLM 多 JSON 幻觉场景下
    会将第一个 { 到最后一个 } 全部吃掉，json.loads 必然失败。
    本模块改用 json.JSONDecoder().raw_decode()，从第一个 { 开始尝试解析，
    天然处理多 JSON / 思维链混杂场景，无需任何正则兜底。
"""
import re
import json
import logging
from typing import Optional

logger = logging.getLogger("json_extractor")

# ==============================================================================
# 阶段一：噪声剥离（COT 思维链 + Markdown 代码块）
# ==============================================================================

def _strip_cot_tags(text: str) -> str:
    """剥离 <thinking> / <think> 思维链标签及其内容。"""
    return re.sub(
        r'<think(?:ing)?[\s\S]*?</think(?:ing)?>',
        '',
        text,
        flags=re.IGNORECASE
    ).strip()


def _strip_markdown_fence(text: str) -> str:
    """
    若 LLM 将 JSON 包裹在 ```json ... ``` 中，提取内层内容。
    仅在确实存在代码块时才提取，避免误伤正常文本。
    """
    pattern = re.compile(r'```(?:json)?\s*([\s\S]*?)\s*```', re.IGNORECASE)
    match = pattern.search(text)
    return match.group(1) if match else text


# ==============================================================================
# 阶段二：核心 JSON 定位（raw_decode 替代贪婪正则）
# ==============================================================================

def _locate_json(text: str) -> Optional[dict]:
    """
    使用 json.JSONDecoder().raw_decode() 从文本中定位第一个合法 JSON 对象。

    原理：raw_decode 从指定 pos 开始解析，遇到第一个完整闭合的 JSON 即停止，
    不受后续文本干扰，完全解决贪婪正则的多 JSON 幻觉崩溃问题。

    若文本中存在前置垃圾（如 "Here is the result: {...}"），
    通过 find('{') 定位第一个 { 作为起始点。
    """
    decoder = json.JSONDecoder()
    start = text.find('{')
    if start == -1:
        return None

    try:
        obj, _ = decoder.raw_decode(text, start)
        return obj
    except json.JSONDecodeError:
        pass

    # 兜底：若 raw_decode 失败（前置内容干扰），逐字符寻找有效起始点
    for i in range(start, len(text)):
        if text[i] == '{':
            try:
                obj, _ = decoder.raw_decode(text, i)
                return obj
            except json.JSONDecodeError:
                continue

    return None


# ==============================================================================
# 阶段三：结构校验（业务无关，仅校验顶层 schema）
# ==============================================================================

def _validate_schema(data: dict, required_key: str = "assets") -> list:
    """
    校验解析结果是否包含指定顶层键，并对每条 asset 执行 V11 Language Protocol 校验。
    返回违规消息列表（空列表 = 全部合规）。
    调用方可根据列表内容决定是否阻断、记录或标记。
    """
    violations = []

    if required_key not in data:
        logger.warning(f"⚠️ 解析结果缺失顶层键: '{required_key}'，返回原始数据供调用方处理。")
        return violations
    if not isinstance(data[required_key], list):
        logger.warning(f"⚠️ '{required_key}' 字段不是列表类型: {type(data[required_key])}")
        return violations

    _CJK = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')

    ENGLISH_FIELDS = [
        ("generative_cornerstones", "t2i_prompt"),
        ("generative_cornerstones", "i2v_prompt"),
        ("generative_cornerstones", "negative_prompt"),
    ]
    CHINESE_FIELDS = [
        ("narrative_analysis", "intent"),
        ("narrative_analysis", "emotional_register"),
        ("narrative_analysis", "friction_scan"),   # v11.1 新增：Phase 0 诊断报告
        ("state_update", "reason"),
    ]

    for idx, asset in enumerate(data[required_key]):
        scene = asset.get("scene_id", f"asset[{idx}]")

        for section, field in ENGLISH_FIELDS:
            value = (asset.get(section) or {}).get(field, "")
            if value and _CJK.search(value):
                msg = f"{scene}.{section}.{field} 含中文（生成提示词须为英文）"
                logger.warning(f"⚠️ [Lang] {msg}: {value[:60]!r}")
                violations.append(msg)

        for section, field in CHINESE_FIELDS:
            value = (asset.get(section) or {}).get(field, "")
            if value and not _CJK.search(value):
                msg = f"{scene}.{section}.{field} 不含中文（叙事字段须为简体中文）"
                logger.warning(f"⚠️ [Lang] {msg}: {value[:60]!r}")
                violations.append(msg)

    return violations


# ==============================================================================
# 公开接口
# ==============================================================================

def extract_json(raw_text: str, required_key: str = "assets") -> dict:
    """
    从 LLM 原始输出中提取第一个合法 JSON 对象。

    处理流程:
        1. 剥离 <thinking> COT 标签
        2. 提取 ```json ``` 代码块内容（如有）
        3. raw_decode 定位第一个闭合 JSON（根除贪婪正则 Bug）
        4. 顶层 schema 校验（仅 warning，不中断）

    Args:
        raw_text:     LLM 返回的原始字符串
        required_key: 期望存在的顶层键名，默认 "assets"

    Returns:
        解析成功 → 原始 dict
        解析失败 → {"assets": [], "_parse_error": true, "_raw_preview": "..."}
    """
    if not raw_text or not raw_text.strip():
        logger.warning("⚠️ extract_json 收到空输入。")
        return {"assets": [], "_parse_error": True, "_raw_preview": ""}

    # 阶段 1: 剥离 COT
    cleaned = _strip_cot_tags(raw_text)

    # 阶段 2: 提取 Markdown 代码块
    cleaned = _strip_markdown_fence(cleaned)

    # 阶段 3: raw_decode 定位 JSON
    data = _locate_json(cleaned)

    if data is None:
        logger.error(
            f"❌ 无法在 LLM 输出中定位有效 JSON。\n"
            f"[原始内容前 300 字]: {raw_text[:300]}"
        )
        return {
            "assets": [],
            "_parse_error": True,
            "_raw_preview": raw_text[:300]
        }

    # 阶段 4: schema 校验，收集 Language Protocol 违规
    violations = _validate_schema(data, required_key)
    if violations:
        data["_lang_violations"] = violations

    return data
