# -*- coding: utf-8 -*-
"""
test_services_v2.py - services_v2 测试护城河
绝对禁止真实 HTTP 请求，全部使用 unittest.mock 拦截。

覆盖场景:
    A. CozeProvider — 正常成功路径
    B. CozeProvider — 提交阶段 502 HTTP Error，重试后耗尽，熔断 raise
    C. CozeProvider — 提交阶段全程 TimeoutException，熔断 raise
    D. CozeProvider — 状态机无限 Pending（poll 耗尽 max_ticks），熔断 raise
    E. CozeProvider — 状态机返回 "failed"，熔断 raise
    F. CozeProvider — completed 但消息列表无 assistant answer，熔断 raise
    G. OpenAIProvider — 正常成功路径
    H. OpenAIProvider — SDK 抛异常，向上 raise
    I. ServiceConfig — 字段默认值正确性
"""
import asyncio
import json
import sys
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services_v2 import ServiceConfig, CozeProvider, OpenAIProvider


# ==============================================================================
# 测试用最小化 Config（把 poll_max_ticks 压到 3，避免测试超长）
# ==============================================================================
def _fast_cfg(**overrides) -> ServiceConfig:
    cfg = ServiceConfig(
        coze_base_url="https://api.coze.cn",
        coze_submit_retries=2,
        coze_retry_sleep=0.0,        # 退避时间归零，测试不等待
        coze_poll_max_ticks=3,       # 压缩轮询次数
        coze_poll_interval=0.0,      # 轮询间隔归零
        openai_timeout=30.0,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _coze(cfg=None) -> CozeProvider:
    return CozeProvider("fake-key", "fake-bot", cfg or _fast_cfg())


# ==============================================================================
# 辅助：构建 Mock httpx Response
# ==============================================================================
def _mock_resp(status_code: int, body: dict) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.text = json.dumps(body)
    r.json.return_value = body
    r.raise_for_status = MagicMock()  # 不抛异常（2xx）
    return r


def _mock_resp_502() -> MagicMock:
    import httpx
    r = MagicMock()
    r.status_code = 502
    r.text = "Bad Gateway"
    r.json.return_value = {}
    # raise_for_status 对 502 会抛，但 CozeProvider 检查 status_code，不调用 raise_for_status
    r.raise_for_status = MagicMock()
    return r


def _coze_submit_ok(chat_id="cid_001", conv_id="conv_001") -> MagicMock:
    return _mock_resp(200, {
        "code": 0,
        "data": {"id": chat_id, "conversation_id": conv_id}
    })


def _poll_resp(status: str) -> MagicMock:
    r = _mock_resp(200, {"data": {"status": status}})
    return r


def _msg_list_resp(content: str) -> MagicMock:
    return _mock_resp(200, {"data": [
        {"role": "assistant", "type": "answer", "content": content}
    ]})


# ==============================================================================
# A. 正常成功路径
# ==============================================================================
class TestCozeProviderSuccess(unittest.IsolatedAsyncioTestCase):

    async def test_happy_path(self):
        """submit 成功 → poll 第一次即 completed → 返回 assistant content"""
        provider = _coze()

        submit_resp  = _coze_submit_ok()
        poll_resp    = _poll_resp("completed")
        msg_resp     = _msg_list_resp('{"assets": []}')

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__  = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=submit_resp)
        mock_client.get  = AsyncMock(side_effect=[poll_resp, msg_resp])

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await provider.generate_content("test prompt")

        self.assertEqual(result, '{"assets": []}')


# ==============================================================================
# B. 提交阶段 502，重试耗尽后熔断
# ==============================================================================
class TestCozeProvider502(unittest.IsolatedAsyncioTestCase):

    async def test_submit_502_exhausts_retries(self):
        """每次 POST 都返回 502，重试次数耗尽后 raise RuntimeError"""
        provider = _coze()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__  = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=_mock_resp_502())

        with patch("httpx.AsyncClient", return_value=mock_client):
            with self.assertRaises(RuntimeError) as ctx:
                await provider.generate_content("test prompt")

        self.assertIn("retries", str(ctx.exception).lower())
        # 验证确实尝试了 coze_submit_retries 次
        self.assertEqual(mock_client.post.call_count, provider.cfg.coze_submit_retries)


# ==============================================================================
# C. 提交阶段 TimeoutException 全程超时
# ==============================================================================
class TestCozeProviderSubmitTimeout(unittest.IsolatedAsyncioTestCase):

    async def test_submit_timeout_all_attempts(self):
        """POST 每次都抛 TimeoutException，最终 raise RuntimeError"""
        import httpx
        provider = _coze()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__  = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            with self.assertRaises(RuntimeError):
                await provider.generate_content("test prompt")

        self.assertEqual(mock_client.post.call_count, provider.cfg.coze_submit_retries)


# ==============================================================================
# D. 状态机无限 Pending — 轮询 max_ticks 耗尽后熔断
# ==============================================================================
class TestCozeProviderPollPendingForever(unittest.IsolatedAsyncioTestCase):

    async def test_poll_pending_exhausts_ticks(self):
        """submit 成功，但 poll 始终返回 in_progress，ticks 耗尽后 raise RuntimeError"""
        provider = _coze()

        submit_resp  = _coze_submit_ok()
        pending_resp = _poll_resp("in_progress")   # 永远 pending

        # 第一个 client（submit 用），第二个（poll 用）
        submit_client = AsyncMock()
        submit_client.__aenter__ = AsyncMock(return_value=submit_client)
        submit_client.__aexit__  = AsyncMock(return_value=False)
        submit_client.post = AsyncMock(return_value=submit_resp)

        poll_client = AsyncMock()
        poll_client.__aenter__ = AsyncMock(return_value=poll_client)
        poll_client.__aexit__  = AsyncMock(return_value=False)
        poll_client.get = AsyncMock(return_value=pending_resp)

        with patch("httpx.AsyncClient", side_effect=[submit_client, poll_client]):
            with self.assertRaises(RuntimeError) as ctx:
                await provider.generate_content("test prompt")

        self.assertIn("polling timeout", str(ctx.exception).lower())
        # 验证确实轮询了 max_ticks 次
        self.assertEqual(poll_client.get.call_count, provider.cfg.coze_poll_max_ticks)


# ==============================================================================
# E. 状态机返回 "failed"
# ==============================================================================
class TestCozeProviderPollFailed(unittest.IsolatedAsyncioTestCase):

    async def test_poll_failed_status_raises(self):
        """poll 返回 failed 状态，应 raise RuntimeError"""
        provider = _coze()

        submit_resp = _coze_submit_ok()
        failed_resp = _poll_resp("failed")

        submit_client = AsyncMock()
        submit_client.__aenter__ = AsyncMock(return_value=submit_client)
        submit_client.__aexit__  = AsyncMock(return_value=False)
        submit_client.post = AsyncMock(return_value=submit_resp)

        poll_client = AsyncMock()
        poll_client.__aenter__ = AsyncMock(return_value=poll_client)
        poll_client.__aexit__  = AsyncMock(return_value=False)
        poll_client.get = AsyncMock(return_value=failed_resp)

        with patch("httpx.AsyncClient", side_effect=[submit_client, poll_client]):
            with self.assertRaises(RuntimeError):
                await provider.generate_content("test prompt")


# ==============================================================================
# F. completed 但消息列表里无 assistant answer
# ==============================================================================
class TestCozeProviderNoAnswer(unittest.IsolatedAsyncioTestCase):

    async def test_completed_no_assistant_answer_raises(self):
        """completed 后消息列表为空（无 assistant answer），应 raise RuntimeError"""
        provider = _coze()

        submit_resp   = _coze_submit_ok()
        completed_resp = _poll_resp("completed")
        empty_msg_resp = _mock_resp(200, {"data": []})   # 空消息列表

        submit_client = AsyncMock()
        submit_client.__aenter__ = AsyncMock(return_value=submit_client)
        submit_client.__aexit__  = AsyncMock(return_value=False)
        submit_client.post = AsyncMock(return_value=submit_resp)

        poll_client = AsyncMock()
        poll_client.__aenter__ = AsyncMock(return_value=poll_client)
        poll_client.__aexit__  = AsyncMock(return_value=False)
        poll_client.get = AsyncMock(side_effect=[completed_resp, empty_msg_resp])

        with patch("httpx.AsyncClient", side_effect=[submit_client, poll_client]):
            with self.assertRaises(RuntimeError):
                await provider.generate_content("test prompt")


# ==============================================================================
# G. OpenAIProvider 正常路径
# ==============================================================================
class TestOpenAIProviderSuccess(unittest.IsolatedAsyncioTestCase):

    async def test_happy_path(self):
        """AsyncOpenAI 正常返回，内容透传"""
        cfg      = _fast_cfg()
        provider = OpenAIProvider("fake-openai-key", cfg)

        mock_choice  = MagicMock()
        mock_choice.message.content = '{"assets": []}'
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_openai_client = AsyncMock()
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

        mock_async_openai_cls = MagicMock(return_value=mock_openai_client)

        with patch.dict("sys.modules", {"openai": MagicMock(AsyncOpenAI=mock_async_openai_cls)}):
            result = await provider.generate_content("test prompt")

        self.assertEqual(result, '{"assets": []}')

        # 验证传入的核心参数
        call_kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
        self.assertEqual(call_kwargs["model"], cfg.openai_model)
        self.assertEqual(call_kwargs["response_format"], {"type": "json_object"})


# ==============================================================================
# H. OpenAIProvider SDK 抛异常后向上 raise
# ==============================================================================
class TestOpenAIProviderError(unittest.IsolatedAsyncioTestCase):

    async def test_sdk_exception_propagates(self):
        """SDK 抛异常时，OpenAIProvider 不吞错误，向上 raise"""
        cfg      = _fast_cfg()
        provider = OpenAIProvider("fake-openai-key", cfg)

        mock_openai_client = AsyncMock()
        mock_openai_client.chat.completions.create = AsyncMock(
            side_effect=Exception("connection refused")
        )
        mock_async_openai_cls = MagicMock(return_value=mock_openai_client)

        with patch.dict("sys.modules", {"openai": MagicMock(AsyncOpenAI=mock_async_openai_cls)}):
            with self.assertRaises(Exception) as ctx:
                await provider.generate_content("test prompt")

        self.assertIn("connection refused", str(ctx.exception))


# ==============================================================================
# I. ServiceConfig 默认值校验
# ==============================================================================
class TestServiceConfig(unittest.TestCase):

    def test_default_paths(self):
        cfg = ServiceConfig()
        self.assertEqual(cfg.coze_chat_path,     "/v3/chat")
        self.assertEqual(cfg.coze_retrieve_path, "/v3/chat/retrieve")
        self.assertEqual(cfg.coze_msg_list_path, "/v3/chat/message/list")

    def test_default_timeouts(self):
        cfg = ServiceConfig()
        self.assertEqual(cfg.coze_submit_timeout, 60.0)
        self.assertEqual(cfg.coze_poll_timeout,   10.0)
        self.assertEqual(cfg.openai_timeout,      90.0)
        self.assertEqual(cfg.chat_sync_timeout,   120.0)

    def test_default_retry_params(self):
        cfg = ServiceConfig()
        self.assertEqual(cfg.coze_submit_retries, 2)
        self.assertEqual(cfg.coze_poll_max_ticks, 40)
        self.assertEqual(cfg.coze_user_id,        "ai_editor_user")
        self.assertEqual(cfg.openai_model,        "gpt-4o")


# ==============================================================================
# 运行入口
# ==============================================================================
if __name__ == "__main__":
    unittest.main(verbosity=2)
