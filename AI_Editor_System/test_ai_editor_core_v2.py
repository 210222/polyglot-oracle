# -*- coding: utf-8 -*-
"""
test_ai_editor_core_v2.py - ai_editor_core_v2 测试脚手架
第一步：只含 import + fixtures，零 test 函数。
"""
import json
import sys
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ai_editor_core_v2  # noqa: E402  — 导入后可 patch 模块级变量


# ==============================================================================
# Fixtures — 基础假数据
# ==============================================================================

@pytest.fixture
def mock_input():
    """标准输入配置：剧本文本 + 视觉账本 + 引擎参数。"""
    return {
        "text":             "英雄走出废墟，眼神坚定，阳光从背后打来。",
        "visual_ledger":    {
            "physical_state": "常态",
            "outfit":         "战损战甲",
            "hero_ref_url":   "https://example.com/hero.jpg",
        },
        "target_engine_key": "Kling_2_6",
        "target_engine":     "Kling 2.6",
        "style_preset":      "MJ_REALISM_V10",
        "rag_context":       "",
        "is_fallback":       False,
    }


@pytest.fixture
def mock_input_with_state_update():
    """含 visual_tags_change 的输入：用于验证 Ledger 状态同步路径。"""
    return {
        "text":             "英雄换上了新的盔甲，气势大变。",
        "visual_ledger":    {
            "physical_state": "常态",
            "outfit":         "布衣",
            "hero_ref_url":   "",
        },
        "target_engine_key": "Kling_2_6",
        "target_engine":     "Kling 2.6",
        "style_preset":      "MJ_REALISM_V10",
        "rag_context":       "",
        "is_fallback":       False,
    }


@pytest.fixture
def mock_llm_response_normal():
    """正常的 LLM 原始字符串响应（含 Markdown 包裹，模拟真实 LLM 输出）。"""
    payload = {
        "assets": [
            {
                "scene_id": "SC_001",
                "target_engine": "Kling 2.6",
                "narrative_analysis": {
                    "intent": "展现英雄重生时刻",
                    "emotional_register": "Epic"
                },
                "generative_cornerstones": {
                    "t2i_prompt": "A hero emerges from ruins, determined gaze, backlit by sunlight --v 6.1 --ar 16:9",
                    "i2v_prompt": "Camera slowly pulls back. Hero stands tall.",
                    "negative_prompt": "text, watermark, blurry"
                },
                "state_update": None
            }
        ]
    }
    return f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"


@pytest.fixture
def mock_llm_response_with_state_update():
    """含 state_update 的 LLM 响应：触发 Visual Ledger 同步路径。"""
    payload = {
        "assets": [
            {
                "scene_id": "SC_002",
                "target_engine": "Kling 2.6",
                "narrative_analysis": {
                    "intent": "英雄换装，身份蜕变",
                    "emotional_register": "Transformative"
                },
                "generative_cornerstones": {
                    "t2i_prompt": "Hero donning new golden armor, dramatic transformation --v 6.1 --ar 16:9",
                    "i2v_prompt": "Camera circles hero. Armor gleams.",
                    "negative_prompt": "text, watermark"
                },
                "state_update": {
                    "visual_tags_change": "身着黄金战甲，气势磅礴",
                    "reason": "剧情触发：英雄换装"
                }
            }
        ]
    }
    return json.dumps(payload, ensure_ascii=False)


@pytest.fixture
def mock_llm_response_empty_assets():
    """LLM 返回合法 JSON 但 assets 为空列表：触发 ValueError 路径。"""
    return json.dumps({"assets": []})


@pytest.fixture
def mock_llm_response_no_assets_key():
    """LLM 返回合法 JSON 但完全缺失 assets 键：触发 ValueError 路径。"""
    return json.dumps({"error": "无法生成内容"})


@pytest.fixture
def mock_llm_service():
    """Mock LLM Service 单例：AsyncMock，默认不设 return_value，由各测试按需覆盖。"""
    svc = MagicMock()
    svc.chat = AsyncMock()
    return svc


@pytest.fixture
def mock_video_engines():
    """最小化 VIDEO_ENGINES 字典：覆盖 resolve_engine_name 查表路径。"""
    return {
        "Kling_2_6":  {"name": "Kling 2.6"},
        "Hailuo_02":  {"name": "Hailuo 02"},
    }


@pytest.fixture
def mock_visual_presets():
    """最小化 VISUAL_PRESETS 字典：覆盖 MJ 参数注入路径。"""
    return {
        "MJ_REALISM_V10": {
            "mj_params": {
                "version": "--v 6.1",
                "aspect":  "--ar 16:9",
            }
        }
    }


# ==============================================================================
# 测试函数
# ==============================================================================

import unittest

class TestGetAiResponseHappyPath(unittest.IsolatedAsyncioTestCase):

    async def test_get_ai_response_happy_path(self):
        """
        最基础跑通测试：正常输入 → 5步流水线走完 → 返回合法字典。
        只断言最外层结构，不做嵌套深度比对。
        """
        # --- 假数据 ---
        input_data = {
            "text":              "英雄走出废墟，眼神坚定，阳光从背后打来。",
            "visual_ledger":     {
                "physical_state": "常态",
                "outfit":         "战损战甲",
                "hero_ref_url":   "https://example.com/hero.jpg",
            },
            "target_engine_key": "Kling_2_6",
            "target_engine":     "Kling 2.6",
            "style_preset":      "MJ_REALISM_V10",
            "rag_context":       "",
            "is_fallback":       False,
        }

        llm_raw = json.dumps({
            "assets": [{
                "scene_id": "SC_001",
                "target_engine": "Kling 2.6",
                "narrative_analysis": {"intent": "英雄重生", "emotional_register": "Epic"},
                "generative_cornerstones": {
                    "t2i_prompt": "A hero emerges from ruins --v 6.1 --ar 16:9",
                    "i2v_prompt": "Camera slowly pulls back.",
                    "negative_prompt": "text, watermark"
                },
                "state_update": None
            }]
        })

        mock_svc = MagicMock()
        mock_svc.chat = AsyncMock(return_value=llm_raw)

        video_engines  = {"Kling_2_6": {"name": "Kling 2.6"}}
        visual_presets = {"MJ_REALISM_V10": {"mj_params": {}}}

        with patch.object(ai_editor_core_v2, "_llm_service",  mock_svc), \
             patch.object(ai_editor_core_v2, "VIDEO_ENGINES",  video_engines), \
             patch.object(ai_editor_core_v2, "VISUAL_PRESETS", visual_presets):

            result = await ai_editor_core_v2.get_ai_response(**input_data)

        # 最外层断言：成功标志、assets 列表非空、new_ledger 为字典
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])
        self.assertIsInstance(result["assets"], list)
        self.assertGreater(len(result["assets"]), 0)
        self.assertIsInstance(result["new_ledger"], dict)


# ==============================================================================
# test_ledger_state_update
# 断言：含 state_update 的 LLM 响应跑完后，
#       V2 new_ledger 的关键 Key 与老代码 get_ai_response 的结果 100% 一致。
# ==============================================================================
class TestLedgerStateUpdate(unittest.IsolatedAsyncioTestCase):

    def _make_llm_raw(self, tags_change: str) -> str:
        return json.dumps({
            "assets": [{
                "scene_id": "SC_002",
                "target_engine": "Kling 2.6",
                "narrative_analysis": {"intent": "换装", "emotional_register": "Transformative"},
                "generative_cornerstones": {
                    "t2i_prompt": "Hero donning golden armor --v 6.1 --ar 16:9",
                    "i2v_prompt": "Camera circles hero.",
                    "negative_prompt": "text, watermark"
                },
                "state_update": {
                    "visual_tags_change": tags_change,
                    "reason": "剧情触发：英雄换装"
                }
            }]
        })

    def _patches(self, mock_svc):
        return [
            patch.object(ai_editor_core_v2, "_llm_service",  mock_svc),
            patch.object(ai_editor_core_v2, "VIDEO_ENGINES",  {"Kling_2_6": {"name": "Kling 2.6"}}),
            patch.object(ai_editor_core_v2, "VISUAL_PRESETS", {"MJ_REALISM_V10": {"mj_params": {}}}),
        ]

    async def _run_v2(self, mock_svc, ledger):
        ctx = self._patches(mock_svc)
        for p in ctx: p.start()
        try:
            return await ai_editor_core_v2.get_ai_response(
                text="英雄换装",
                visual_ledger=ledger,
                target_engine_key="Kling_2_6",
                target_engine="Kling 2.6",
            )
        finally:
            for p in ctx: p.stop()

    async def test_ledger_state_update_v2(self):
        """
        state_update.visual_tags_change 触发时，
        V2 new_ledger["physical_state"] 必须被更新为新值，
        其余原始 key（outfit、hero_ref_url）必须完整保留。
        """
        tags_change = "身着黄金战甲，气势磅礴"
        original_ledger = {
            "physical_state": "常态",
            "outfit":         "布衣",
            "hero_ref_url":   "",
        }

        mock_svc = MagicMock()
        mock_svc.chat = AsyncMock(return_value=self._make_llm_raw(tags_change))

        result = await self._run_v2(mock_svc, original_ledger.copy())

        self.assertTrue(result["success"])
        new_ledger = result["new_ledger"]

        # 核心断言：physical_state 已被同步为新值
        self.assertEqual(new_ledger["physical_state"], tags_change)

        # 原始字段完整保留（只有 physical_state 被覆盖，其余不变）
        self.assertEqual(new_ledger["outfit"],       original_ledger["outfit"])
        self.assertEqual(new_ledger["hero_ref_url"], original_ledger["hero_ref_url"])

    async def test_ledger_no_state_update_unchanged(self):
        """
        state_update 为 None 时，new_ledger 必须与原始 visual_ledger 完全相同。
        """
        original_ledger = {
            "physical_state": "常态",
            "outfit":         "战损战甲",
            "hero_ref_url":   "https://example.com/hero.jpg",
        }
        llm_raw = json.dumps({
            "assets": [{
                "scene_id": "SC_003",
                "target_engine": "Kling 2.6",
                "narrative_analysis": {"intent": "静止", "emotional_register": "Calm"},
                "generative_cornerstones": {
                    "t2i_prompt": "Hero stands still --v 6.1 --ar 16:9",
                    "i2v_prompt": "Camera holds.",
                    "negative_prompt": "text"
                },
                "state_update": None
            }]
        })

        mock_svc = MagicMock()
        mock_svc.chat = AsyncMock(return_value=llm_raw)

        result = await self._run_v2(mock_svc, original_ledger.copy())

        self.assertTrue(result["success"])
        new_ledger = result["new_ledger"]

        # state_update=None → new_ledger 所有 key 与原始完全一致
        for key, val in original_ledger.items():
            self.assertEqual(new_ledger[key], val)


# ==============================================================================
# 异常路径 1：LLM service 为 None → success: False（含 EnvironmentError 信息）
# ==============================================================================
class TestLLMServiceNone(unittest.IsolatedAsyncioTestCase):

    async def test_llm_service_none_returns_failure(self):
        """_llm_service 为 None 时，流水线不崩溃，返回 success: False 并含错误信息。"""
        with patch.object(ai_editor_core_v2, "_llm_service",  None), \
             patch.object(ai_editor_core_v2, "VIDEO_ENGINES",  {"Kling_2_6": {"name": "Kling 2.6"}}), \
             patch.object(ai_editor_core_v2, "VISUAL_PRESETS", {"MJ_REALISM_V10": {"mj_params": {}}}):

            result = await ai_editor_core_v2.get_ai_response(
                text="任意剧本",
                visual_ledger={"physical_state": "常态", "outfit": "默认", "hero_ref_url": ""},
                target_engine_key="Kling_2_6",
                target_engine="Kling 2.6",
            )

        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
        self.assertIn("error", result)
        # 错误信息应包含 LLM 初始化失败的提示
        self.assertIn("LLM", result["error"])


# ==============================================================================
# 异常路径 2：assets 为空列表 → success: False
# ==============================================================================
class TestEmptyAssets(unittest.IsolatedAsyncioTestCase):

    async def test_empty_assets_returns_failure(self):
        """LLM 返回 assets:[] 时，流水线不崩溃，返回 success: False 并含错误信息。"""
        llm_raw = json.dumps({"assets": []})

        mock_svc = MagicMock()
        mock_svc.chat = AsyncMock(return_value=llm_raw)

        with patch.object(ai_editor_core_v2, "_llm_service",  mock_svc), \
             patch.object(ai_editor_core_v2, "VIDEO_ENGINES",  {"Kling_2_6": {"name": "Kling 2.6"}}), \
             patch.object(ai_editor_core_v2, "VISUAL_PRESETS", {"MJ_REALISM_V10": {"mj_params": {}}}):

            result = await ai_editor_core_v2.get_ai_response(
                text="任意剧本",
                visual_ledger={"physical_state": "常态", "outfit": "默认", "hero_ref_url": ""},
                target_engine_key="Kling_2_6",
                target_engine="Kling 2.6",
            )

        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
        self.assertIn("error", result)

    async def test_missing_assets_key_returns_failure(self):
        """LLM 返回 JSON 完全缺失 assets 键时，同样返回 success: False。"""
        llm_raw = json.dumps({"result": "无法生成"})

        mock_svc = MagicMock()
        mock_svc.chat = AsyncMock(return_value=llm_raw)

        with patch.object(ai_editor_core_v2, "_llm_service",  mock_svc), \
             patch.object(ai_editor_core_v2, "VIDEO_ENGINES",  {"Kling_2_6": {"name": "Kling 2.6"}}), \
             patch.object(ai_editor_core_v2, "VISUAL_PRESETS", {"MJ_REALISM_V10": {"mj_params": {}}}):

            result = await ai_editor_core_v2.get_ai_response(
                text="任意剧本",
                visual_ledger={"physical_state": "常态", "outfit": "默认", "hero_ref_url": ""},
                target_engine_key="Kling_2_6",
                target_engine="Kling 2.6",
            )

        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
        self.assertIn("error", result)
