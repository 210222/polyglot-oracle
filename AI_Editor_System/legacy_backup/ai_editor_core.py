# -*- coding: utf-8 -*-
"""
ai_editor_core.py - v12.0 Polyglot Oracle Facade Layer (Full Async + V11 Soul)
[Refactor]:
    1. [ASYNC] get_ai_response / ai_editor_inference 全部改为 async def，
       LLM 调用改为 await llm_service.chat()，接通异步链路。
    2. [V11 FIX] 从 config 导入 SYSTEM_PROMPT_V11_0（兼容别名 SYSTEM_PROMPT_POLYGLOT），
       废弃旧版 _call_openai 绕过写法。
    3. [ENGINE FIX] target_engine 参数严格注入 Prompt 的 [TARGET ENGINE] 数据流，
       LLM 可精确感知当前引擎并执行 Phase C 适配规则。
    4. 后处理逻辑（Ledger 同步、MJ 参数注入、负向词清洗）完整保留。
"""
import asyncio
import json
import logging
import re
from typing import Dict, Any, List

# --- 服务组件导入 ---
try:
    from services import llm_service
except ImportError as e:
    logging.warning(f"⚠️ services 加载失败，将使用 Mock 模式运行。Error: {e}")
    llm_service = None

# ChromaDB 可选依赖，缺失不影响主流程
try:
    from ingest_engine.components.chroma_adapter import ChromaRepository
except ImportError:
    ChromaRepository = None

# --- 逻辑层导入 (已切换至 logic_v2，BN-01/02/03/05 全部修复) ---
try:
    from logic_v2 import (
        IntelligentRAGLayer,
        sanitize_syntax,
        sanitize_negative_prompts,
        smart_json_extractor
    )
except ImportError:
    def sanitize_syntax(x): return x
    def sanitize_negative_prompts(x): return x
    # 兜底使用 json_extractor 的安全解析（无贪婪正则）
    try:
        from json_extractor import extract_json as smart_json_extractor
    except ImportError:
        def smart_json_extractor(x): return json.loads(re.search(r'\{[\s\S]*?\}', x).group(0))

# --- 配置层导入 ---
try:
    # SYSTEM_PROMPT_V11_0 是权威变量名，SYSTEM_PROMPT_POLYGLOT 是其兼容别名，二者等价
    from config import SYSTEM_PROMPT_V11_0, VISUAL_PRESETS, VIDEO_ENGINES
except ImportError:
    SYSTEM_PROMPT_V11_0 = "Error: Config missing."
    VISUAL_PRESETS = {}
    VIDEO_ENGINES = {}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ai_editor_core")

# ==============================================================================
# 🧠 兜底知识库 (Fallback Knowledge — RAG 不可用时使用)
# ==============================================================================
FALLBACK_KNOWLEDGE = """
[INTERNAL EXPERT KNOWLEDGE BASE - FALLBACK MODE]
1. LIGHTING: Cinematic lighting, volumetric scattering, dramatic shadows, neon undertones.
2. CAMERA: Low angle shot, 85mm lens, shallow depth of field, steady tripod.
3. VIBE: High fidelity, photorealistic, 8k resolution, Unreal Engine 5 render style.
"""

# ==============================================================================
# 🛠️ 辅助清理函数 (Phase B — MJ 参数注入)
# ==============================================================================
def cleanup_midjourney_syntax(t2i_prompt: str, ledger: dict, mj_params: dict) -> str:
    """清理并注入 Midjourney 专属参考图参数 (Phase B 逻辑)"""
    base_prompt = sanitize_syntax(t2i_prompt)

    ref_url = ledger.get("hero_ref_url", "")
    if ref_url and "--cref" not in base_prompt:
        base_prompt += f" --cref {ref_url} --cw 100"

    for key, val in mj_params.items():
        if str(val).split()[0] not in base_prompt:
            base_prompt += f" {val}"

    return base_prompt.strip()


# ==============================================================================
# 🚀 核心编排引擎 (The Commander) — 全异步
# ==============================================================================
async def get_ai_response(
    text: str,
    visual_ledger: dict,
    target_engine_key: str,
    target_engine: str = "Kling 2.6",
    style_preset: str = "MJ_REALISM_V10",
    rag_context: str = "",
    is_fallback: bool = False
) -> dict:
    """
    接收剧本、视觉账本和目标引擎，异步调用 LLM，输出格式化的分镜提示词。

    参数:
        text            : 用户输入的线性剧本文本
        visual_ledger   : 当前视觉账本 JSON（人物状态、服装、参考图 URL）
        target_engine_key: VIDEO_ENGINES 字典中的 Key（如 "Kling_2_6"）
        target_engine   : 直接传入的引擎显示名（如 "Kling 2.6"），优先于 key 查表
        style_preset    : VISUAL_PRESETS 中的预设 Key
        rag_context     : 外部 RAG 检索结果（空则使用内置兜底知识库）
        is_fallback     : 标记本次是否使用兜底模式（影响 meta_data 中的 rag_source 字段）
    """
    # 1. 解析引擎名称：优先用调用方直接传入的 target_engine，其次从字典查表
    engine_from_dict = VIDEO_ENGINES.get(target_engine_key, {}).get("name", "")
    target_engine_name = target_engine if target_engine else engine_from_dict or "Kling 2.6"
    logger.info(f"🚀 Polyglot Oracle 启动 | 目标引擎: {target_engine_name}")

    # 2. RAG 知识库内容装载
    context = rag_context if rag_context else FALLBACK_KNOWLEDGE

    # 3. 严格按照 V11 格式组装四大数据流 (The Oracle Protocol)
    #    [TARGET ENGINE] 字段显式注入引擎名，确保 LLM Phase C 适配规则精确触发
    oracle_input = f"""
[VISUAL LEDGER]:
{json.dumps(visual_ledger, ensure_ascii=False, indent=2)}

[USER SCRIPT]:
{text}

[TARGET ENGINE]:
{target_engine_name}

[DATABASE CONTEXT (RAG)]:
{context}
"""

    # 系统 Meta-Prompt (V11_0) + 数据流拼接
    full_prompt = f"{SYSTEM_PROMPT_V11_0}\n\n{oracle_input}"

    try:
        # 4. 异步调用统一 LLM 网关（不再绕过 chat()，不再阻塞事件循环）
        if llm_service is None:
            raise EnvironmentError("LLM Service 未初始化，请检查 services.py 导入。")

        raw_response = await llm_service.chat(full_prompt)

        # 5. 暴力 JSON 提取（穿透 Deep CoT 思维链与 Markdown 包裹）
        parsed_data = smart_json_extractor(raw_response)
        assets = parsed_data.get("assets", [])

        # 6. 后处理与状态同步
        style_cfg = VISUAL_PRESETS.get(style_preset, VISUAL_PRESETS.get("MJ_REALISM_V10", {}))
        mj_params = style_cfg.get("mj_params", {})

        new_ledger = visual_ledger.copy()

        if isinstance(assets, list) and len(assets) > 0:
            for asset in assets:
                # -- A. 挂载 Meta 数据供排错使用 --
                if "meta_data" not in asset:
                    asset["meta_data"] = {}
                asset["meta_data"]["ledger_snapshot"] = visual_ledger.copy()
                asset["meta_data"]["engine_used"] = target_engine_name
                asset["meta_data"]["rag_source"] = "Built-in Expert" if is_fallback else "Local Database"

                # -- B. T2I 提示词格式化清理（注入 MJ 参数与人脸参考）--
                gc = asset.get("generative_cornerstones", {})
                t2i_raw = gc.get("t2i_prompt", "")
                asset["generative_cornerstones"]["t2i_prompt"] = cleanup_midjourney_syntax(
                    t2i_raw, visual_ledger, mj_params
                )
                # -- B2. I2V 提示词清洗（剔除混入的 MJ 参数语法）--
                asset["generative_cornerstones"]["i2v_prompt"] = sanitize_negative_prompts(
                    gc.get("i2v_prompt", "")
                )

                # -- C. 拦截并处理 Visual State Delta（同步到新账本）--
                state_update = asset.get("state_update")
                if state_update and isinstance(state_update, dict):
                    tags_change = state_update.get("visual_tags_change")
                    if tags_change:
                        new_ledger["physical_state"] = str(tags_change)
                        logger.info(
                            f"🔄 Visual Ledger 更新命中! 新状态: {tags_change} "
                            f"(原因: {state_update.get('reason')})"
                        )

            return {"success": True, "assets": assets, "new_ledger": new_ledger}

        else:
            return {"success": False, "error": "大模型返回的 JSON 缺失 assets 字段。"}

    except Exception as e:
        logger.error(f"Oracle Execution Failed: {e}")
        return {"success": False, "error": str(e)}


# ==============================================================================
# 🔌 向下兼容包装器 (Legacy Wrapper) — 异步版
# ==============================================================================
async def ai_editor_inference(
    text: str, task: str = "剧情润色", user_id: str = "default"
) -> dict:
    """
    兼容旧版 main.py / app.py 的过渡接口（现已升级为 async）。
    默认使用 Kling 2.6 引擎，dummy_ledger 提供最小化账本。
    """
    logger.info(f"收到兼容层 API 请求 | task={task} | user={user_id}")
    dummy_ledger = {"physical_state": "常态", "outfit": "默认服饰", "hero_ref_url": ""}

    res = await get_ai_response(
        text=text,
        visual_ledger=dummy_ledger,
        target_engine_key="Kling_2_6",
        target_engine="Kling 2.6"
    )

    if res["success"]:
        formatted_result = (
            f"### 🎭 Polyglot 生成结果\n\n"
            f"```json\n{json.dumps(res['assets'], ensure_ascii=False, indent=2)}\n```"
        )
        return {"success": True, "data": formatted_result}

    return {"success": False, "error": res.get("error")}
