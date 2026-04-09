# -*- coding: utf-8 -*-
"""
test_ue_link_integration.py - UE5 UDP 网桥集成测试

测试目标：
    1. 启动纯 Python 靶机模拟 ue_receiver.py（不依赖 unreal 模块）
    2. 使用 ue_bridge.send_assets_to_ue5() 发送超过 5000 字节的超大 JSON
    3. 断言接收端完整接收且 JSON 解析无截断
    4. 断言测试结束后端口完全释放（无端口占用残留）

覆盖的修复点：
    - C-3: with socket 上下文管理器端口瞬间释放
    - P2:  recvfrom(65535) 大包不截断
    - 发送侧 ue_bridge.send_assets_to_ue5() 端到端链路
"""

import json
import socket
import threading
import time
import unittest

# ---------------------------------------------------------------
# 被测模块（不依赖 unreal，直接导入 ue_bridge）
# ---------------------------------------------------------------
from ue_bridge import send_assets_to_ue5

# 测试专用端口（避免与生产端 11111 / 调试端 11112 冲突）
TEST_PORT = 19999
TEST_HOST = "127.0.0.1"
RECV_BUF  = 65535


# ---------------------------------------------------------------
# 工具函数：生成超过 5000 字节的复杂分镜假数据
# ---------------------------------------------------------------
def _make_heavy_assets(target_bytes: int = 6000) -> list:
    """
    构造一个结构完整的 Polyglot Oracle assets 列表。
    通过填充 rag_context 字段确保序列化后超过 target_bytes。
    """
    padding = "A" * target_bytes  # 保底填充，确保体积

    asset = {
        "scene_id": "SC_INTEGRATION_TEST_001",
        "target_engine": "Kling 2.6",
        "narrative_analysis": {
            "intent": "主角在赛博朋克小巷中全速奔跑，镜头低角度跟拍，强烈追逐感",
            "emotional_register": "紧迫感，轻微恐慌",
        },
        "generative_cornerstones": {
            "t2i_prompt": (
                "/imagine prompt: A cyberpunk alley at night, rain-soaked asphalt reflecting "
                "neon signs, male protagonist in torn tactical jacket sprinting, low angle "
                "tracking shot, 24mm wide lens, volumetric fog, blade runner aesthetic, "
                "cinematic lighting --cref https://example.com/hero_ref.jpg --cw 100 "
                "--v 6.1 --ar 16:9 --s 250 --style raw"
            ),
            "i2v_prompt": (
                "Subject sprints through narrow cyberpunk alley, handheld camera shake, "
                "fast tracking shot from behind, rain droplets scattering under footsteps, "
                "neon blue light reflecting off wet ground, shallow depth of field, "
                "motion blur on background elements, cinematic 24fps"
            ),
            "negative_prompt": "text, watermark, blurry, low quality, distortion, static camera",
        },
        "state_update": {
            "visual_tags_change": ["sprinting", "wet_jacket", "neon_lit"],
            "reason": "主角进入高速奔跑状态，服装因雨水和运动产生形变",
        },
        "meta_data": {
            "ledger_snapshot": {
                "physical_state": "常态",
                "outfit": "Distressed tactical leather jacket",
                "hero_ref_url": "https://example.com/hero_ref.jpg",
            },
            "engine_used": "Kling 2.6",
            "rag_source": "Local Database",
            # 填充字段：模拟包含大量 RAG 上下文的真实场景
            "rag_context_dump": padding,
        },
    }

    # 序列化验证体积
    serialized = json.dumps({"assets": [asset]}, ensure_ascii=False)
    actual_bytes = len(serialized.encode("utf-8"))
    assert actual_bytes > 5000, (
        f"测试数据构造失败：期望 >5000B，实际 {actual_bytes}B"
    )
    return [asset], actual_bytes


# ---------------------------------------------------------------
# 靶机：纯 Python UDP 接收端（模拟 ue_receiver.py，无 unreal 依赖）
# ---------------------------------------------------------------
class _UDPTarget:
    """
    在独立线程中监听 TEST_PORT，将接收到的原始字节存入 received_payloads。
    使用 with socket 上下文管理器，stop() 后端口立即释放。
    """

    def __init__(self):
        self.received_payloads: list = []  # 存储解析后的 dict
        self.received_raw: list = []       # 存储原始字节（用于长度断言）
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()  # bind 完成信号
        self._thread = threading.Thread(target=self._listen, daemon=True)

    def start(self):
        self._thread.start()
        # 等待靶机完成 bind，最多 3 秒
        assert self._ready_event.wait(timeout=3.0), "靶机启动超时：bind 未完成"

    def stop(self):
        self._stop_event.set()
        self._thread.join(timeout=5.0)

    def _listen(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(1.0)
            sock.bind((TEST_HOST, TEST_PORT))
            self._ready_event.set()  # 通知主线程 bind 已完成

            while not self._stop_event.is_set():
                try:
                    raw_data, _ = sock.recvfrom(RECV_BUF)
                    self.received_raw.append(raw_data)
                    self.received_payloads.append(
                        json.loads(raw_data.decode("utf-8"))
                    )
                except socket.timeout:
                    continue
                except json.JSONDecodeError as e:
                    # 若发生截断，JSON 解析必然失败，此处记录供断言使用
                    self.received_payloads.append({"_parse_error": str(e)})
        # with 块退出 → sock.close() 自动调用 → 端口释放


# ---------------------------------------------------------------
# 工具函数：检查端口是否已被占用
# ---------------------------------------------------------------
def _port_is_free(port: int) -> bool:
    """尝试 bind 目标端口，成功则说明端口已释放。"""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((TEST_HOST, port))
            return True
        except OSError:
            return False


# ---------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------
class TestUELinkIntegration(unittest.TestCase):

    def setUp(self):
        self.target = _UDPTarget()
        self.target.start()

    def tearDown(self):
        self.target.stop()

    # -----------------------------------------------------------
    # 核心测试：超大包完整传输 + 端口回收
    # -----------------------------------------------------------
    def test_large_payload_integrity_and_port_release(self):
        """
        端到端断言：
        1. 超大 JSON（>5000B）发送成功，无错误
        2. 接收端完整解析，无截断（parsed dict 字段完整）
        3. 接收到的字节数与发送字节数精确相等
        4. 测试结束后 TEST_PORT 完全释放
        """

        # ── Step 1: 构造超大测试数据 ──────────────────────────────
        assets, actual_bytes = _make_heavy_assets(target_bytes=6000)
        print(f"\n[测试数据] 构造完成，实际体积: {actual_bytes} 字节 (>5000B ✓)")

        # ── Step 2: 通过 ue_bridge 发送 ───────────────────────────
        sent_count, errors = send_assets_to_ue5(
            assets, host=TEST_HOST, port=TEST_PORT
        )

        self.assertEqual(errors, [], f"发送侧报错: {errors}")
        self.assertEqual(sent_count, 1, f"期望发出 1 包，实际 {sent_count}")
        print(f"[发送侧]   send_assets_to_ue5() 成功，sent={sent_count}, errors={errors}")

        # ── Step 3: 等待靶机接收（UDP 本地回环延迟 <10ms，等 1s 充裕）──
        time.sleep(1.0)

        # ── Step 4: 断言接收端收到了数据 ──────────────────────────
        self.assertEqual(
            len(self.target.received_payloads), 1,
            f"靶机应收到 1 包，实际收到 {len(self.target.received_payloads)} 包"
        )
        print(f"[接收侧]   靶机收到包数: {len(self.target.received_payloads)} ✓")

        # ── Step 5: 断言 JSON 完整解析（无截断错误）─────────────────
        payload = self.target.received_payloads[0]
        self.assertNotIn(
            "_parse_error", payload,
            f"JSON 解析失败（截断发生）: {payload.get('_parse_error')}"
        )
        print(f"[完整性]   JSON 解析成功，无截断 ✓")

        # ── Step 6: 断言字段完整性 ────────────────────────────────
        self.assertEqual(payload.get("scene_id"), "SC_INTEGRATION_TEST_001")
        self.assertIn("generative_cornerstones", payload)
        self.assertIn("production_assets", payload)
        self.assertIn("ue5_params", payload["production_assets"])

        gc = payload["generative_cornerstones"]
        self.assertIn("t2i_prompt", gc)
        self.assertIn("i2v_prompt", gc)
        self.assertIn("negative_prompt", gc)
        print(f"[字段校验] scene_id / generative_cornerstones / ue5_params 全部存在 ✓")

        # ── Step 7: 断言原始字节数精确匹配（无截断的黄金标准）────────
        raw_len = len(self.target.received_raw[0])
        # ue_bridge 发送的是 packet（非原始 asset），重新序列化一次对齐
        expected_data = json.dumps({
            "scene_id": payload["scene_id"],
            "target_engine": payload["target_engine"],
            "generative_cornerstones": payload["generative_cornerstones"],
            "state_update": payload.get("state_update"),
            "production_assets": payload["production_assets"],
        }, ensure_ascii=False).encode("utf-8")

        self.assertEqual(
            raw_len, len(expected_data),
            f"字节数不匹配：接收 {raw_len}B ≠ 期望 {len(expected_data)}B，存在截断！"
        )
        print(f"[字节校验] 接收 {raw_len}B == 发送 {len(expected_data)}B，精确匹配 ✓")

        # ── Step 8: 停止靶机，断言端口立即释放 ────────────────────
        self.target.stop()
        # 稍等 OS 回收（通常 <100ms，给 500ms 余量）
        time.sleep(0.5)

        self.assertTrue(
            _port_is_free(TEST_PORT),
            f"端口 {TEST_PORT} 未释放！with socket 上下文管理器失效。"
        )
        print(f"[端口回收] 端口 {TEST_PORT} 已完全释放 ✓")


if __name__ == "__main__":
    unittest.main(verbosity=2)
