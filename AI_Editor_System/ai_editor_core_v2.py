# -*- coding: utf-8 -*-
"""
ai_editor_core_v2.py - 拆分重构实现层
将 get_ai_response 巨无霸拆分为 5 个单一职责子函数。
主函数 get_ai_response 作为纯 Pipeline 调度器，不超过 15 行。
"""
import json
import logging
import os
from typing import Dict, List, Tuple, Any, Callable

# --- 配置层导入 ---
try:
    from config import SYSTEM_PROMPT_V11_0, VISUAL_PRESETS, VIDEO_ENGINES, FALLBACK_KNOWLEDGE
except ImportError:
    SYSTEM_PROMPT_V11_0 = "Error: Config missing."
    VISUAL_PRESETS = {}
    VIDEO_ENGINES = {}
    FALLBACK_KNOWLEDGE = ""

# --- 逻辑层导入 ---
try:
    from logic_v2 import (
        sanitize_syntax as _sanitize_syntax,
        sanitize_negative_prompts as _sanitize_i2v,
        smart_json_extractor as _json_extractor,
    )
except ImportError:
    def _sanitize_syntax(x): return x
    def _sanitize_i2v(x): return x
    def _json_extractor(x): return json.loads(x)

# --- 服务层导入（V2 策略模式网关，替代 V1 monolith）---
try:
    from services_v2 import llm_service as _llm_service
except ImportError:
    _llm_service = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ai_editor_core_v2")


# ==============================================================================
# Phase 1 — 解析输入
# ==============================================================================
def resolve_engine_name(
    target_engine: str,
    target_engine_key: str,
    video_engines: Dict[str, Any],
) -> str:
    """
    解析最终使用的引擎显示名。
    优先使用调用方直接传入的 target_engine，
    其次从 VIDEO_ENGINES 字典按 key 查表，
    兜底返回 "Kling 2.6"。
    """
    engine_from_dict = video_engines.get(target_engine_key, {}).get("name", "")
    return target_engine if target_engine else engine_from_dict or "Kling 2.6"


# ==============================================================================
# Phase 1.5 — 格式化引擎规则（[ENGINE RULES] 数据流生成）
# ==============================================================================
def _format_engine_rules(engine_name: str, engine_cfg: Dict[str, Any]) -> str:
    """
    将 VIDEO_ENGINES[key] 的 description + adapter_rules 转换为 LLM 可读规则文本。
    修复 Prompt Phase C 承诺 "ENGINE RULE injected below" 但注入为空的问题。
    例句按引擎按需注入，不占用 System Prompt Token。
    """
    lines = [f"Name: {engine_name}"]
    if engine_cfg.get("description"):
        lines.append(f"Core Constraint: {engine_cfg['description']}")
    adapter = engine_cfg.get("adapter_rules", {})
    if adapter.get("require_bracket_commands"):
        lines.append(
            "REQUIRED: i2v_prompt MUST contain [bracket] camera commands "
            "(e.g. [Push in], [Zoom out], [Shake])."
        )
    if adapter.get("strip_static_pattern"):
        lines.append(
            "WARNING: i2v_prompt must describe MOTION and PHYSICS only. "
            "Do NOT include outfit / hair / eye color descriptions."
        )
    t2i_triggers = adapter.get("t2i_trigger_words", [])
    if t2i_triggers:
        lines.append(f"REQUIRED t2i trigger words: {', '.join(t2i_triggers)}")
    if adapter.get("warn_if_visual_description"):
        lines.append(
            "WARNING: i2v_prompt must identify character by ROLE/IDENTITY, "
            "NOT physical appearance (no hair/eyes/wearing descriptions)."
        )

    # 按引擎注入对应例句（从 System Prompt 抽出，节省约 800 chars Token）
    _examples = {
        "Kling 2.6": (
            'Example i2v: "Detective lurches forward through flooded alley, '
            'waterlogged coat dragging with gravitational weight, rain-disturbed '
            'puddles rippling outward, steam rising from grates, low handheld '
            'tracking shot following subject with micro-tremor, anamorphic shallow DOF, '
            'in the final beat camera slows to reveal neon reflection in puddle"'
        ),
        "即梦 AI Video": (
            'Example i2v (Chinese ok): "主角踉跄冲入街道，积水在脚步间四溅，'
            '低角度手持跟拍，浅景深"'
        ),
        "Hailuo Video-01": (
            'Example i2v: "[Slow push in, Tilt up] Detective lurches through '
            'rain-flooded alley, coat billowing with wind resistance, neon-lit '
            'puddles rippling underfoot, steam vents erupting in background"'
        ),
        "Luma Ray 3": (
            'Example i2v: "The camera drifts slowly forward as the detective trudges '
            'through the rain-soaked alley, each heavy footfall sending ripples across '
            'flooded cobblestones, warm tungsten light painting subsurface glow across '
            'rain-drenched skin, resolving into medium close-up as subject pauses"'
        ),
        "Google Veo 3.1": (
            'Example i2v: "[00:00-00:04] Low-angle handheld tracking shot, veteran '
            'detective lurches through rain-flooded alley, volumetric neon cutting '
            'through steam. [00:04-00:08] Slow push-in close-up, detective pivots '
            'and scans shadows, deep penumbra, cyan neon color bleed. No text, no crowd"'
        ),
    }
    example = _examples.get(engine_name)
    if example:
        lines.append(example)

    return "\n".join(lines)


# ==============================================================================
# Phase 2 — 组装 Prompt
# ==============================================================================
def build_oracle_prompt(
    text: str,
    visual_ledger: Dict[str, Any],
    target_engine_name: str,
    engine_rules: str,
    rag_context: str,
    system_prompt: str,
    fallback_knowledge: str,
) -> str:
    """
    按 V11 Oracle Protocol 格式组装完整 Prompt。
    包含五大数据流注入：
        [VISUAL LEDGER] / [USER SCRIPT] / [TARGET ENGINE] / [ENGINE RULES] / [DATABASE CONTEXT (RAG)]
    engine_rules 来自 _format_engine_rules()，兑现 Phase C "ENGINE RULE injected below" 承诺。
    rag_context 为空时自动使用 fallback_knowledge。
    """
    def _assemble(ctx: str) -> str:
        oracle_input = f"""
[VISUAL LEDGER]:
{json.dumps(visual_ledger, ensure_ascii=False, indent=2)}

[USER SCRIPT]:
{text}

[TARGET ENGINE]:
{target_engine_name}

[ENGINE RULES]:
{engine_rules}

[DATABASE CONTEXT (RAG)]:
{ctx}
"""
        return f"{system_prompt}\n\n{oracle_input}"

    context = rag_context if rag_context else fallback_knowledge
    prompt  = _assemble(context)

    # Upgrade 2 — Token budget guard（中英混合近似估算，误差 < 15%）
    # 中文字符: ~2 tokens/char；其余字符（英文/标点）按 ~0.25 tokens/char 估算
    cn_chars = sum(1 for c in prompt if '\u4e00' <= c <= '\u9fff')
    token_estimate = cn_chars * 2 + (len(prompt) - cn_chars) // 4
    if token_estimate > 8000 and rag_context:
        logger.warning(
            f"⚠️ Token budget: ~{token_estimate} tokens > 8000 阈值，"
            f"丢弃 RAG ({len(rag_context)} chars) → 使用 FALLBACK_KNOWLEDGE。"
        )
        prompt = _assemble(fallback_knowledge)

    return prompt


# ==============================================================================
# Phase 3 — 调用大模型
# ==============================================================================
async def call_llm(
    full_prompt: str,
    llm_service: Any,
) -> str:
    """
    异步调用统一 LLM 网关，返回原始字符串响应。
    llm_service 为 None 时抛出 EnvironmentError。
    不做任何解析，只负责网络调用和错误透传。
    """
    if llm_service is None:
        raise EnvironmentError("LLM Service 未初始化，请检查 services.py 导入。")
    return await llm_service.chat(full_prompt)


# ==============================================================================
# Phase 4 — 清洗 JSON
# ==============================================================================
def extract_and_validate_assets(
    raw_response: str,
    json_extractor: Callable,
) -> List[Dict[str, Any]]:
    """
    穿透 Deep CoT 思维链与 Markdown 包裹，提取并验证 assets 列表。
    使用 json_extractor (smart_json_extractor) 安全解析。
    assets 为空或缺失时抛出 ValueError，由上层统一处理。
    返回合法的 assets 列表。
    """
    parsed = json_extractor(raw_response)

    # ① _parse_error 哨兵：优先于一切结构校验，避免"合法 JSON"误导消息
    if parsed.get("_parse_error"):
        preview = parsed.get("_raw_preview", "")[:120]
        raise ValueError(
            "LLM 输出 JSON 解析失败，无法从原始响应中提取合法结构。"
            f" 原始预览: {preview!r}"
        )

    # ① (b) Mock 污染哨兵：MockProvider 降级返回含 MOCK_SCENE_001 的合法 JSON，
    # 结构校验完全通过但数据无意义。在此处拦截，让错误可见而非静默成功。
    if "MOCK_SCENE_001" in raw_response:
        raise RuntimeError(
            "LLM Provider 降级至 Mock 模式（API Key 无效或网络不通）。"
            "请检查 .env 中的 COZE_API_KEY / OPENAI_API_KEY 配置，当前返回的是占位符数据。"
        )

    # ② Language Protocol 违规透传（非阻断，记录后继续）
    lang_violations = parsed.get("_lang_violations", [])
    if lang_violations:
        logger.warning(
            f"⚠️ Language Protocol 违规 {len(lang_violations)} 处，资产已通过但质量存疑: "
            f"{lang_violations}"
        )

    if "assets" not in parsed or parsed["assets"] is None:
        raise ValueError(
            "大模型返回的 JSON 缺失 assets 字段（null / 键不存在）。"
        )

    assets = parsed["assets"]

    if not isinstance(assets, list):
        raise TypeError(
            f"assets 字段类型错误，期望 list，实际为 {type(assets).__name__}。"
        )

    if len(assets) == 0:
        raise ValueError(
            "大模型返回了合法 JSON，但 assets 为空列表（[]）。"
            " 请检查 Prompt 是否触发了 LLM 拒绝或输出截断。"
        )
    return assets


# ==============================================================================
# Phase 5 — 后处理与状态同步
# ==============================================================================
def postprocess_assets(
    assets: List[Dict[str, Any]],
    visual_ledger: Dict[str, Any],
    target_engine_name: str,
    is_fallback: bool,
    mj_params: Dict[str, str],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    对每条 asset 执行三项后处理，返回 (processed_assets, new_ledger)：
        A. 挂载 meta_data（ledger_snapshot / engine_used / rag_source）
        B. T2I 提示词清洗并注入 MJ 参数与 --cref 人脸参考
        B2. I2V 提示词清洗（剔除混入的 MJ 参数语法）
        C. 拦截 state_update.visual_tags_change，同步到 new_ledger
    new_ledger 是 visual_ledger 的拷贝，仅在有 state_update 时被修改。
    """
    import copy
    new_ledger = copy.deepcopy(visual_ledger)

    for asset in assets:
        # A. 挂载 meta_data
        if "meta_data" not in asset:
            asset["meta_data"] = {}
        asset["meta_data"]["ledger_snapshot"] = copy.deepcopy(visual_ledger)
        asset["meta_data"]["engine_used"]     = target_engine_name
        asset["meta_data"]["rag_source"]      = "Built-in Expert" if is_fallback else "Local Database"

        # B. T2I 提示词清洗 + MJ 参数注入
        asset.setdefault("generative_cornerstones", {})
        gc      = asset["generative_cornerstones"]
        t2i_raw = gc.get("t2i_prompt", "")
        asset["generative_cornerstones"]["t2i_prompt"] = _cleanup_t2i(
            t2i_raw, visual_ledger, mj_params,
            asset.get("state_update")
        )

        # B2. I2V 提示词清洗
        asset["generative_cornerstones"]["i2v_prompt"] = _sanitize_i2v(
            gc.get("i2v_prompt", "")
        )

        # C. Visual State Delta → 同步到 new_ledger
        state_update = asset.get("state_update")
        if state_update and isinstance(state_update, dict):
            # C1. physical_state（泥污、撕裂、流血等物理痕迹）
            tags_change = state_update.get("visual_tags_change")
            if isinstance(tags_change, list) and len(tags_change) > 0:
                new_ledger["physical_state"] = tags_change
                logger.info(
                    f"Physical State 更新命中! 新状态: {tags_change} "
                    f"(原因: {state_update.get('reason')})"
                )
                # C1b. Outfit tag 兜底提升（LLM 未使用 hero_outfit_change 字段时）
                if not state_update.get("hero_outfit_change"):
                    _OUTFIT_KW = {"outfit", "wear", "wearing", "clothing", "costume",
                                  "dress", "mask", "armor", "uniform", "jacket", "coat"}
                    outfit_tags = [t for t in tags_change
                                   if any(kw in str(t).lower() for kw in _OUTFIT_KW)]
                    if outfit_tags:
                        new_ledger["outfit"] = ", ".join(str(t) for t in outfit_tags)
                        logger.warning(
                            f"⚠️ Outfit tags 从 visual_tags_change 提升: {outfit_tags}。"
                            f"建议 LLM 使用专属字段 hero_outfit_change。"
                        )
            elif tags_change == []:
                logger.warning("⚠️ visual_tags_change 为空列表，已自动修正为 null")
                asset["state_update"]["visual_tags_change"] = None

            # C2. hero_outfit_change（换装、加装备、摘面具等服饰变更）
            outfit_change = state_update.get("hero_outfit_change")
            if outfit_change and isinstance(outfit_change, str) and outfit_change.strip():
                new_ledger["outfit"] = outfit_change
                logger.info(
                    f"Outfit Ledger 更新命中! 新服装: {outfit_change} "
                    f"(原因: {state_update.get('reason')})"
                )

        # D. edit_bridge 直通（LLM 输出字段，仅做存在性保障，不修改内容）
        if "edit_bridge" not in asset:
            asset["edit_bridge"] = {"cut_type": "hard_cut", "transition_note": "", "pacing": "medium"}

    return assets, new_ledger


# ==============================================================================
# Phase 6 — 代码层 Engine Adapter（保障层，不依赖 LLM 记忆 Phase C 规则）
# ==============================================================================
def apply_engine_adapter(asset: dict, engine_key: str) -> dict:
    """
    读取 VIDEO_ENGINES[engine_key].adapter_rules，对 asset 执行后处理。
    作为 Phase C 的代码层保障：即使 LLM 幻觉或输出截断导致 Phase C 未遵守，
    此函数仍能兜底修正 i2v_prompt / t2i_prompt，并对违规输出发出 warning。

    规则覆盖：
        strip_static_pattern    : 用正则从 i2v_prompt 剥离静态外观词（Kling 专用）
        t2i_trigger_words       : 强制追加触发词到 t2i_prompt（Luma 专用）
        strip_negative_pattern  : 清除负向语义短语（Luma 专用）
        strip_negative_from_i2v : 从 i2v_prompt 清除负向提示词语法
        require_bracket_commands: 校验 Hailuo i2v_prompt 必须含 [xxx] 指令
        warn_if_visual_description: Google Veo 警告含外观描述的 i2v_prompt
    """
    import re as _re
    rules = VIDEO_ENGINES.get(engine_key, {}).get("adapter_rules", {})
    if not rules:
        return asset

    gc  = asset.get("generative_cornerstones", {})
    i2v = gc.get("i2v_prompt", "")
    t2i = gc.get("t2i_prompt", "")

    # 规则 1: 剥离静态外观词（Kling）
    if rules.get("strip_static_pattern"):
        i2v = _re.sub(rules["strip_static_pattern"], "", i2v, flags=_re.IGNORECASE).strip(", ")

    # 规则 2: 清除 i2v 中的负向提示词语法（--no / negative: 等）
    if rules.get("strip_negative_from_i2v"):
        i2v = _re.sub(r'--no\s+\S+', "", i2v, flags=_re.IGNORECASE).strip()

    # 规则 3: 清除负向语义短语（Luma）
    if rules.get("strip_negative_pattern"):
        i2v = _re.sub(rules["strip_negative_pattern"], "", i2v, flags=_re.IGNORECASE).strip()

    # 规则 4: 强制注入触发词到 t2i_prompt（Luma）
    for trigger in rules.get("t2i_trigger_words", []):
        if trigger.lower() not in t2i.lower():
            t2i = t2i.rstrip(", ") + f", {trigger}"

    # 规则 5: 校验 Hailuo 中括号运镜指令
    if rules.get("require_bracket_commands") and not _re.search(r'\[.+?\]', i2v):
        logger.warning(
            f"⚠️ [Adapter:{engine_key}] Hailuo i2v_prompt 缺少 [运镜] 指令，"
            f"LLM 可能未遵守 Phase C 规则: {i2v[:80]!r}"
        )

    # 规则 6: Google Veo — 警告含外观描述的 i2v_prompt
    if rules.get("warn_if_visual_description"):
        _visual_pattern = r'\b(wearing|dressed in|hair|eyes|skin|tall|short|appearance)\b'
        if _re.search(_visual_pattern, i2v, flags=_re.IGNORECASE):
            logger.warning(
                f"⚠️ [Adapter:{engine_key}] Veo i2v_prompt 含外观描述词，"
                f"应改用角色身份描述: {i2v[:80]!r}"
            )

    gc["i2v_prompt"] = i2v
    gc["t2i_prompt"]  = t2i.strip(", ")
    asset["generative_cornerstones"] = gc
    return asset


# ==============================================================================
# 辅助：MJ 参数注入（Phase B — --cw 动态感知换装状态）
# ==============================================================================
def _cleanup_t2i(t2i_prompt: str, ledger: dict, mj_params: dict,
                 state_update: dict = None) -> str:
    """
    清洗 T2I 提示词并注入 Midjourney 专属参数。

    --cw 值动态决策（对齐 V11 Phase B Anchor Check 规则）：
      - 服装未变（state_update 无 outfit 相关 tag）→ --cw 100（面部 + 服装全锚定）
      - 服装已变（tags 含 outfit/wear/clothing/costume）→ --cw 20（仅锚定面部）
    """
    base = _sanitize_syntax(t2i_prompt)
    ref_url = (ledger or {}).get("hero_ref_url", "")

    if ref_url and "--cref" not in base:
        # 检查 state_update 中是否有服装变化 tag
        outfit_changed = False
        if state_update and isinstance(state_update, dict):
            # 主路径：hero_outfit_change 字段（A-3 新增，LLM 规范输出时优先使用）
            # 与 Phase B 规则对齐：此字段非 null 即表示换装，直接触发 --cw 20
            if state_update.get("hero_outfit_change"):
                outfit_changed = True
            else:
                # 兜底路径：扫描 visual_tags_change 关键词（LLM 未使用 hero_outfit_change 时）
                tags = state_update.get("visual_tags_change") or []
                outfit_keywords = {"outfit", "wear", "wearing", "clothing", "costume", "dress"}
                outfit_changed = any(
                    any(kw in str(tag).lower() for kw in outfit_keywords)
                    for tag in tags
                )
        cw_value = 20 if outfit_changed else 100
        base += f" --cref {ref_url} --cw {cw_value}"

    for key, val in mj_params.items():
        if str(val).split()[0] not in base:
            base += f" {val}"
    return base.strip()


# ==============================================================================
# 🚀 主函数 Pipeline 调度器（≤15 行）
# ==============================================================================
# ==============================================================================
# RAG 健康检查（轻量级，无 Embedding 模型加载，仅探测 DB 存活状态）
# ==============================================================================
def get_rag_health() -> str:
    """
    检查 ChromaDB 向量库的真实健康状态。
    不加载 Embedding 模型，仅通过 PersistentClient 做存活与数据量探测。
    返回格式化状态字符串，供 web_ui.py 顶栏展示。
    """
    try:
        import chromadb
        from config import DB_PATH
    except ImportError as e:
        return f"⚠️ RAG 依赖缺失: {e}"

    if not os.path.isdir(DB_PATH):
        return f"🔴 RAG 离线 (DB 路径不存在: {os.path.basename(DB_PATH)})"

    try:
        client = chromadb.PersistentClient(path=DB_PATH)
        collections = client.list_collections()

        if not collections:
            return "🟡 RAG 空库 (0 个集合，请先运行 run_ingest.py)"

        total_docs = sum(c.count() for c in collections)
        col_names = ", ".join(c.name for c in collections[:3])
        if len(collections) > 3:
            col_names += f" +{len(collections) - 3}"

        if total_docs == 0:
            return f"🟡 RAG 空数据 ({len(collections)} 个集合，0 条向量)"

        return f"🟢 RAG 就绪 ({total_docs} 条向量 | {col_names})"

    except Exception as e:
        return f"🔴 RAG 异常: {str(e)[:60]}"


# ==============================================================================
# Upgrade 1 — LLM 调用 + 自修复重试（最多 3 次，含首次）
# ==============================================================================

def _classify_repair_failure(raw: str, exc: Exception) -> str:
    """
    分析原始 LLM 输出，返回故障类型标识符：
      TRUNCATED    — JSON 没有闭合括号（响应被截断）
      WRAPPED      — Markdown 代码块或 <thinking> 残留在 JSON 外
      EMPTY_ASSETS — LLM 返回了合法 JSON 但 assets 为空列表
      CORRUPT      — 其他乱码/结构损坏，不可重试
    """
    raw_stripped = raw.strip()
    if raw_stripped and not raw_stripped.endswith(('}', ']')):
        return "TRUNCATED"
    if '```' in raw or ('</' in raw and '{' in raw):
        return "WRAPPED"
    if '"assets": []' in raw or '"assets":[]' in raw:
        return "EMPTY_ASSETS"
    return "CORRUPT"


async def _llm_with_repair(
    full_prompt: str,
    llm_service: Any,
    json_extractor: Callable,
) -> List[Dict[str, Any]]:
    """
    调用 LLM 并在 JSON 解析失败时注入对症 repair_hint 引导自修复。

    两条路径：
      - TRUNCATED / WRAPPED / EMPTY_ASSETS（可修复型）：注入 hint，最多重试 2 次。
      - CORRUPT（不可修复型）：记录原始预览，直接 raise，不浪费 token 重试。
    """
    repair_hint = ""
    for attempt in range(3):
        prompt = full_prompt + repair_hint if repair_hint else full_prompt
        raw    = await call_llm(prompt, llm_service)
        try:
            return extract_and_validate_assets(raw, json_extractor)
        except (ValueError, TypeError, RuntimeError) as e:
            failure_type = _classify_repair_failure(raw, e)

            if failure_type == "CORRUPT":
                logger.error(f"Corrupt response (attempt {attempt + 1}), raw preview: {raw[:200]!r}")
                raise

            if attempt < 2:
                if failure_type == "TRUNCATED":
                    repair_hint = (
                        "\n\n[REPAIR]: Your previous response was cut off. "
                        "Continue from the last valid JSON position and complete the structure. "
                        "Output ONLY the remaining JSON, starting from where it was cut."
                    )
                elif failure_type == "WRAPPED":
                    repair_hint = (
                        "\n\n[REPAIR]: Output ONLY raw JSON. "
                        "No markdown fences. No <thinking> after the JSON closing brace."
                    )
                elif failure_type == "EMPTY_ASSETS":
                    repair_hint = (
                        "\n\n[REPAIR]: You returned an empty assets array. "
                        "You MUST generate at least one asset for the provided script."
                    )
                logger.warning(
                    f"Oracle attempt {attempt + 1}/3 failed "
                    f"[{failure_type}], injecting repair hint"
                )
            else:
                logger.error(f"Oracle attempt 3/3 exhausted [{failure_type}]: {e}")
                raise
    raise RuntimeError("unreachable")


async def get_ai_response(
    text: str,
    visual_ledger: dict,
    target_engine_key: str,
    target_engine: str = "Kling 2.6",
    style_preset: str = "MJ_REALISM_V10",
    rag_context: str = "",
    is_fallback: bool = False,
) -> dict:
    """Pipeline 调度器：按序调用子函数，含 JSON 自修复最多 3 次重试。"""
    try:
        visual_ledger = visual_ledger or {}   # 防御 None Ledger：Session 未初始化时兜底空字典
        engine_name  = resolve_engine_name(target_engine, target_engine_key, VIDEO_ENGINES)
        engine_rules = _format_engine_rules(engine_name, VIDEO_ENGINES.get(target_engine_key, {}))
        logger.info(f"Polyglot Oracle 启动 | 目标引擎: {engine_name}")
        _sys_prompt  = VISUAL_PRESETS.get(style_preset, {}).get("system_prompt", SYSTEM_PROMPT_V11_0)
        full_prompt  = build_oracle_prompt(text, visual_ledger, engine_name, engine_rules, rag_context, _sys_prompt, FALLBACK_KNOWLEDGE)
        assets       = await _llm_with_repair(full_prompt, _llm_service, _json_extractor)
        mj_params    = VISUAL_PRESETS.get(style_preset, VISUAL_PRESETS.get("MJ_REALISM_V10", {})).get("mj_params", {})
        assets, new_ledger = postprocess_assets(assets, visual_ledger, engine_name, is_fallback, mj_params)
        assets = [apply_engine_adapter(a, target_engine_key) for a in assets]
        return {"success": True, "assets": assets, "new_ledger": new_ledger}
    except Exception as e:
        logger.error(f"Oracle Execution Failed: {e}")
        return {"success": False, "error": str(e)}
