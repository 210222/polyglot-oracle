# -*- coding: utf-8 -*-
"""
test_logic_v2.py - logic_v2 测试护城河
覆盖场景:
    A. JSON 解析器 (json_extractor)
       A1. 正常 JSON 输出
       A2. LLM 多 JSON 幻觉（BN-01 贪婪正则崩溃场景）
       A3. <thinking> COT 包裹的 JSON
       A4. ```json ``` Markdown 代码块包裹
       A5. 完全破损 / 空输入
       A6. JSON 存在但缺失 assets 顶层键

    B. 提示词清洗器 (prompt_sanitizer)
       B1. T2I 正常清洗
       B2. T2I 参数冲突 last-win
       B3. I2V 清除混入的 MJ 参数
       B4. 非字符串输入防御

    C. RAG 分桶格式化器 (rag_formatter)
       C1. 正常分桶（WORLD_RULES / TECH_SPECS / REFERENCES）
       C2. is_vip=true 优先落入 WORLD_RULES
       C3. 空输入返回兜底字符串
       C4. reorder_primacy_recency 首尾重排正确性
       C5. 超出 bucket limit 的条目被截断
"""
import sys
import os
import unittest

# 确保从 AI_Editor_System 目录加载模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from json_extractor import extract_json
from prompt_sanitizer import sanitize_t2i_prompt, sanitize_i2v_prompt
from rag_formatter import format_rag_context, reorder_primacy_recency


# ==============================================================================
# A. JSON 解析器测试
# ==============================================================================
class TestJsonExtractor(unittest.TestCase):

    # A1: 正常干净的 JSON
    def test_normal_json(self):
        raw = '{"assets": [{"scene_id": "SC_001", "generative_cornerstones": {}}]}'
        result = extract_json(raw)
        self.assertIn("assets", result)
        self.assertEqual(result["assets"][0]["scene_id"], "SC_001")
        self.assertNotIn("_parse_error", result)

    # A2: 多 JSON 幻觉 —— BN-01 核心回归测试
    # 原贪婪正则会将两个 JSON 之间的所有内容一起匹配，json.loads 必然失败
    # raw_decode 应正确解析第一个闭合 JSON，忽略后续内容
    def test_multiple_json_hallucination(self):
        raw = (
            'Here is my thinking: {"debug": "intermediate", "step": 1} '
            'And the final answer: {"assets": [{"scene_id": "SC_002"}]}'
        )
        result = extract_json(raw)
        # 应解析到第一个 JSON（debug 字段），不应崩溃
        self.assertNotIn("_parse_error", result)
        self.assertIsInstance(result, dict)

    # A3: <thinking> COT 标签包裹
    def test_strip_cot_thinking_tags(self):
        raw = (
            '<thinking>我需要分析剧本，考虑以下因素...</thinking>'
            '{"assets": [{"scene_id": "SC_003"}]}'
        )
        result = extract_json(raw)
        self.assertIn("assets", result)
        self.assertEqual(result["assets"][0]["scene_id"], "SC_003")

    # A4: Markdown 代码块包裹
    def test_strip_markdown_fence(self):
        raw = '```json\n{"assets": [{"scene_id": "SC_004"}]}\n```'
        result = extract_json(raw)
        self.assertIn("assets", result)
        self.assertEqual(result["assets"][0]["scene_id"], "SC_004")

    # A5-a: 完全破损输入（无任何 JSON）
    def test_broken_no_json(self):
        raw = "对不起，我无法生成合适的内容。请重试。"
        result = extract_json(raw)
        self.assertEqual(result["assets"], [])
        self.assertTrue(result.get("_parse_error"))

    # A5-b: 空字符串输入
    def test_empty_input(self):
        result = extract_json("")
        self.assertEqual(result["assets"], [])
        self.assertTrue(result.get("_parse_error"))

    # A5-c: None 类型防御（不应抛异常）
    def test_none_input(self):
        result = extract_json(None)
        self.assertEqual(result["assets"], [])
        self.assertTrue(result.get("_parse_error"))

    # A6: JSON 合法但缺失 assets 键（应返回数据但触发 warning）
    def test_missing_assets_key(self):
        raw = '{"result": "ok", "data": []}'
        result = extract_json(raw)
        # 不应崩溃，应返回原始 dict
        self.assertIn("result", result)
        self.assertNotIn("_parse_error", result)


# ==============================================================================
# B. 提示词清洗器测试
# ==============================================================================
class TestPromptSanitizer(unittest.TestCase):

    # B1: T2I 正常清洗 —— 占位符移除 + 参数提取
    def test_t2i_removes_placeholders(self):
        prompt = "A hero [State] in [Env] --v 6.1 --ar 16:9"
        result = sanitize_t2i_prompt(prompt)
        self.assertNotIn("[State]", result)
        self.assertNotIn("[Env]", result)
        self.assertIn("--v", result)
        self.assertIn("--ar", result)

    # B2: T2I 参数冲突 last-win —— 同一参数出现两次，保留后者
    def test_t2i_param_conflict_last_wins(self):
        prompt = "Beautiful scene --ar 16:9 some text --ar 3:2"
        result = sanitize_t2i_prompt(prompt)
        # last-win: 3:2 应保留，16:9 被覆盖
        self.assertIn("3:2", result)

    # B3: I2V 清除混入的 MJ 参数
    def test_i2v_strips_mj_params(self):
        prompt = "Camera tracks subject --v 6.1 --ar 16:9 running fast"
        result = sanitize_i2v_prompt(prompt)
        self.assertNotIn("--v", result)
        self.assertNotIn("--ar", result)
        self.assertIn("running fast", result)

    # B4: 非字符串输入防御
    def test_t2i_non_string_input(self):
        self.assertEqual(sanitize_t2i_prompt(None), "")
        self.assertEqual(sanitize_t2i_prompt(123), "")

    def test_i2v_non_string_input(self):
        self.assertEqual(sanitize_i2v_prompt(None), "")


# ==============================================================================
# C. RAG 分桶格式化器测试
# ==============================================================================
class TestRagFormatter(unittest.TestCase):

    def _make_doc(self, content, source="unknown", category="general",
                  language="zh", is_vip=False):
        return {
            "content": content,
            "metadata": {
                "source": source,
                "kb_category": category,
                "language": language,
                "is_vip": str(is_vip)
            }
        }

    # C1: 正常三桶分类
    def test_normal_bucket_routing(self):
        docs = [
            self._make_doc("拍摄规则：不得使用手持", source="rulebook"),
            self._make_doc("焦距建议 85mm", category="director_spec"),
            self._make_doc("一般参考内容", source="misc"),
        ]
        result = format_rag_context(docs)
        self.assertIn("WORLD_RULES", result)
        self.assertIn("VISUAL_SPECS", result)
        self.assertIn("REFERENCES", result)

    # C2: is_vip=true 强制进入 WORLD_RULES
    def test_vip_doc_goes_to_world_rules(self):
        docs = [
            self._make_doc("VIP 内容", source="random_source", is_vip=True),
        ]
        result = format_rag_context(docs)
        self.assertIn("WORLD_RULES", result)
        self.assertNotIn("REFERENCES", result)

    # C3: 空输入返回兜底字符串
    def test_empty_input_returns_fallback(self):
        result = format_rag_context([])
        self.assertEqual(result, "(No relevant knowledge found)")

    # C4: reorder_primacy_recency 首尾重排正确性（修复 BN-03）
    def test_reorder_correctness(self):
        docs = ["A", "B", "C", "D", "E"]
        result = reorder_primacy_recency(docs)
        # A（最重要）在首位，B（次重要）在末位，其余在中间
        self.assertEqual(result[0], "A")
        self.assertEqual(result[-1], "B")
        self.assertIn("C", result[1:-1])
        self.assertIn("D", result[1:-1])
        self.assertIn("E", result[1:-1])

    # C4b: 少于 3 条时不应重排
    def test_reorder_short_list(self):
        self.assertEqual(reorder_primacy_recency([]), [])
        self.assertEqual(reorder_primacy_recency(["A"]), ["A"])
        self.assertEqual(reorder_primacy_recency(["A", "B"]), ["A", "B"])

    # C5: 超出 limit 的条目被截断（REFERENCES 上限为 3）
    def test_bucket_limit_respected(self):
        docs = [self._make_doc(f"参考内容 {i}", source="misc") for i in range(10)]
        result = format_rag_context(docs)
        # REFERENCES 桶上限 3 条，10 条输入只应输出 3 条
        references_section = result.split("<SECTION: REFERENCES>")[-1] if "<SECTION: REFERENCES>" in result else ""
        entry_count = references_section.count("\n- ")
        self.assertLessEqual(entry_count, 3)


# ==============================================================================
# 运行入口
# ==============================================================================
if __name__ == "__main__":
    unittest.main(verbosity=2)
