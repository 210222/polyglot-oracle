# -*- coding: utf-8 -*-
"""
services_v2.py - 策略模式重构 (第一步: 骨架层)
只含 ServiceConfig 数据类 + BaseLLMProvider 抽象基类。
"""
import os
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from dotenv import load_dotenv

load_dotenv()  # 保证无论谁先 import 都能读到 .env key，不依赖调用方的加载顺序


@dataclass
class ServiceConfig:
    """
    集中管理所有硬编码的 URL、路径和数值常量。
    实例化后可被各 Provider 注入使用。
    """
    # --- Coze Base URL (可被 .env 覆盖) ---
    coze_base_url: str = field(
        default_factory=lambda: os.getenv("COZE_BASE_URL", "https://api.coze.cn")
    )

    # --- Coze API 路径 ---
    coze_chat_path: str = "/v3/chat"
    coze_retrieve_path: str = "/v3/chat/retrieve"
    coze_msg_list_path: str = "/v3/chat/message/list"

    # --- Coze Payload 固定字段 ---
    coze_user_id: str = "ai_editor_user"

    # --- Coze 超时 (秒) ---
    coze_submit_timeout: float = 60.0   # POST 提交超时
    coze_poll_timeout: float = 10.0     # 每次轮询 GET 超时
    coze_msg_timeout: float = 30.0      # completed 后消息获取超时（独立字段，需比轮询超时更长）

    # --- Coze 重试 ---
    coze_submit_retries: int = 2        # 提交最大尝试次数 (range(2))
    coze_retry_sleep: float = 2.0       # 重试间隔

    # --- Coze 轮询 ---
    coze_poll_max_ticks: int = 40       # 最大轮询次数 (range(40))
    coze_poll_interval: float = 1.5     # 每次轮询间隔

    # --- OpenAI Base URL (可被 .env 覆盖) ---
    openai_base_url: str = field(
        default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    )

    # --- OpenAI 固定字段 ---
    openai_model: str = "gpt-4o"
    openai_timeout: float = 90.0

    # --- OpenAI Standard 兼容接口 (DeepSeek / 智谱 / 任意代理) ---
    openai_std_base_url: str = field(
        default_factory=lambda: os.getenv("OPENAI_STD_BASE_URL", "https://api.deepseek.com/v1")
    )
    openai_std_model: str = field(
        default_factory=lambda: os.getenv("OPENAI_STD_MODEL", "deepseek-chat")
    )
    openai_std_timeout: float = 90.0
    openai_std_retries: int = 2

    # --- chat_sync 线程池超时 ---
    chat_sync_timeout: float = 120.0


class BaseLLMProvider(ABC):
    """
    所有 LLM Provider 的抽象基类 (策略模式接口)。
    具体实现: CozeProvider / OpenAIProvider / MockProvider。
    """

    @abstractmethod
    async def generate_content(self, prompt: str) -> str:
        """
        向 LLM 发送 prompt，异步返回原始字符串响应。
        失败时应返回可被下游解析的合法字符串，不得抛出异常。
        """
        ...


# ==============================================================================
# OpenAI Provider
# ==============================================================================
class OpenAIProvider(BaseLLMProvider):
    """
    OpenAI / 兼容代理接口的异步实现。
    完整保留老代码业务参数：model、system prompt、response_format。
    """

    def __init__(self, api_key: str, config: ServiceConfig):
        self.api_key = api_key
        self.cfg = config

    async def generate_content(self, prompt: str) -> str:
        """
        修复 C-2（V11 Prompt 角色错位）：
        - full_prompt = SYSTEM_PROMPT_V11_0 + oracle_input，以 [VISUAL LEDGER] 为分隔点
        - 分隔点之前 → system 消息（角色定义 + Phase A-D + Language Protocol）
        - 分隔点之后 → user 消息（四大数据流：Ledger / Script / Engine / RAG）
        - 移除 response_format=json_object，保留 LLM 自由输出 CoT，
          由 smart_json_extractor 穿透提取 JSON。
        """
        import logging
        _log = logging.getLogger("services_v2.openai")
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.cfg.openai_base_url,
                timeout=self.cfg.openai_timeout,
            )

            # 按 oracle_input 起始标记拆分 system / user
            split_marker = "\n\n[VISUAL LEDGER]:"
            if split_marker in prompt:
                idx = prompt.index(split_marker)
                system_part = prompt[:idx].strip()
                user_part   = prompt[idx:].strip()
            else:
                system_part = "You are a professional cinematic AI pipeline assistant."
                user_part   = prompt

            response = await client.chat.completions.create(
                model=self.cfg.openai_model,
                messages=[
                    {"role": "system", "content": system_part},
                    {"role": "user",   "content": user_part},
                ]
                # 不使用 response_format=json_object：
                # 该参数会截断 CoT 思维链，与 V11 Deep CoT 设计冲突。
                # smart_json_extractor 负责从自由文本中穿透提取 JSON。
            )
            return response.choices[0].message.content
        except Exception as e:
            _log.error(f"OpenAI call failed: {e}")
            raise


# ==============================================================================
# OpenAI Standard Provider（纯 httpx，零 SDK 依赖，兼容 DeepSeek / 智谱 / 任意代理）
# ==============================================================================
class OpenAIStandardProvider(BaseLLMProvider):
    """
    对接任意 OpenAI /chat/completions 兼容接口（DeepSeek、智谱 GLM 等）。
    使用纯 httpx，无需安装 openai SDK，无轮询，带指数退避重试。
    """

    def __init__(self, api_key: str, config: ServiceConfig):
        self.api_key = api_key
        self.cfg     = config
        self._log    = __import__("logging").getLogger("services_v2.openai_std")

    async def generate_content(self, prompt: str) -> str:
        import httpx, asyncio
        url     = self.cfg.openai_std_base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        split_marker = "\n\n[VISUAL LEDGER]:"
        if split_marker in prompt:
            idx         = prompt.index(split_marker)
            system_part = prompt[:idx].strip()
            user_part   = prompt[idx:].strip()
        else:
            system_part = "You are a professional cinematic AI pipeline assistant."
            user_part   = prompt

        payload = {
            "model":    self.cfg.openai_std_model,
            "messages": [
                {"role": "system", "content": system_part},
                {"role": "user",   "content": user_part},
            ],
        }

        for attempt in range(self.cfg.openai_std_retries):
            try:
                async with httpx.AsyncClient(timeout=self.cfg.openai_std_timeout) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code != 200:
                    self._log.error(f"OpenAI Std HTTP {resp.status_code}: {resp.text[:200]}")
                    await asyncio.sleep(self.cfg.coze_retry_sleep * (2 ** attempt))
                    continue
                return resp.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError) as e:
                self._log.error(f"OpenAI Std response structure error: {e}")
                raise
            except httpx.TimeoutException:
                self._log.warning(f"OpenAI Std attempt {attempt + 1} timed out.")
                await asyncio.sleep(self.cfg.coze_retry_sleep * (2 ** attempt))
            except Exception as e:
                self._log.warning(f"OpenAI Std attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(self.cfg.coze_retry_sleep * (2 ** attempt))

        raise RuntimeError(f"OpenAI Std API failed after {self.cfg.openai_std_retries} retries.")


# ==============================================================================
# Coze Provider
# ==============================================================================
class CozeProvider(BaseLLMProvider):
    """
    Coze v3 API 的异步实现（submit + poll 两阶段状态机）。
    新增：基于 asyncio.sleep 的指数退避重试 + 超时熔断。
    业务参数与老代码 100% 对齐：payload 字段、状态判断、消息提取逻辑。
    """

    def __init__(self, api_key: str, bot_id: str, config: ServiceConfig):
        self.api_key = api_key
        self.bot_id  = bot_id
        self.cfg     = config
        self._log    = __import__("logging").getLogger("services_v2.coze")

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------
    async def generate_content(self, prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        }
        chat_url = self.cfg.coze_base_url.rstrip("/") + self.cfg.coze_chat_path
        # 按 oracle_input 起始标记拆分 system / user（与 OpenAIProvider 及 services.py 对齐）
        split_marker = "\n\n[VISUAL LEDGER]:"
        if split_marker in prompt:
            idx         = prompt.index(split_marker)
            system_part = prompt[:idx].strip()
            user_part   = prompt[idx:].strip()
        else:
            system_part = ""
            user_part   = prompt

        # Coze meta_data.value 上限 512 字符，无法承载完整 System Prompt。
        # 将 system_part 合并到 user 消息头部，Oracle 指令完整传达，无字符数限制。
        combined = f"{system_part}\n\n{user_part}" if system_part else user_part

        payload  = {
            "bot_id":  self.bot_id,
            "user_id": self.cfg.coze_user_id,
            "stream":  False,
            "additional_messages": [
                {"role": "user", "content": combined, "content_type": "text"}
            ],
        }

        import httpx, asyncio

        # --- 提交阶段：带指数退避重试 ---
        for attempt in range(self.cfg.coze_submit_retries):
            try:
                async with httpx.AsyncClient(timeout=self.cfg.coze_submit_timeout) as client:
                    resp = await client.post(chat_url, headers=headers, json=payload)

                if resp.status_code != 200:
                    self._log.error(
                        f"Coze HTTP Error {resp.status_code}: {resp.text[:200]}"
                    )
                    await self._backoff(attempt)
                    continue

                data = resp.json()
                if data.get("code") != 0:
                    self._log.error(f"Coze API Logic Error: {data.get('msg')}")
                    await self._backoff(attempt)
                    continue

                chat_id         = data["data"]["id"]
                conversation_id = data["data"]["conversation_id"]
                return await self._poll(chat_id, conversation_id, headers)

            except (RuntimeError, ValueError, TimeoutError):
                # _poll 的致命信号（任务失败 / 无内容 / 超时熔断），直接穿透，不计入提交重试
                raise
            except httpx.TimeoutException:
                self._log.warning(f"Coze submit attempt {attempt + 1} timed out.")
                await self._backoff(attempt)
            except Exception as e:
                self._log.warning(f"Coze submit attempt {attempt + 1} failed: {e}")
                await self._backoff(attempt)

        raise RuntimeError("Coze API failed after all submit retries.")

    # ------------------------------------------------------------------
    # 轮询阶段（超时熔断：max_ticks × poll_interval）
    # ------------------------------------------------------------------
    async def _poll(self, chat_id: str, conversation_id: str, headers: dict) -> str:
        import httpx, asyncio

        base    = self.cfg.coze_base_url.rstrip("/")
        ret_url = f"{base}{self.cfg.coze_retrieve_path}?chat_id={chat_id}&conversation_id={conversation_id}"
        msg_url = f"{base}{self.cfg.coze_msg_list_path}?chat_id={chat_id}&conversation_id={conversation_id}"

        for tick in range(self.cfg.coze_poll_max_ticks):
            try:
                # 每个 tick 独立 client，彻底隔离 keep-alive 死连接复用（对齐 services.py C-2 修复）
                async with httpx.AsyncClient(timeout=self.cfg.coze_poll_timeout) as client:
                    resp = await client.get(ret_url, headers=headers)
                    resp.raise_for_status()
                    status = resp.json().get("data", {}).get("status")

                    if status == "completed":
                        # 独立重试循环：与轮询 except 隔离，防止 msg_url 超时被外层
                        # httpx.TimeoutException 捕获后继续空转轮询直到 max_ticks 耗尽。
                        for msg_attempt in range(3):
                            try:
                                async with httpx.AsyncClient(timeout=self.cfg.coze_msg_timeout) as msg_client:
                                    m_resp = await msg_client.get(msg_url, headers=headers)
                                    m_resp.raise_for_status()
                                    for msg in reversed(m_resp.json().get("data", [])):
                                        if msg.get("role") == "assistant" and msg.get("type") == "answer":
                                            return msg["content"]
                                    raise ValueError("Coze completed but no assistant answer found.")
                            except ValueError:
                                raise   # 无 answer 是致命错误，穿透到外层 (RuntimeError, ValueError): raise
                            except Exception as e:
                                self._log.warning(f"Coze msg fetch attempt {msg_attempt + 1}/3 failed: {e}")
                                if msg_attempt < 2:
                                    await asyncio.sleep(2)
                        raise RuntimeError("Coze completed but msg fetch failed after 3 attempts.")

                    elif status == "failed":
                        raise RuntimeError("Coze task reported failed status.")

            except (RuntimeError, ValueError):
                raise  # 致命错误：立即向上穿透，不进入重试循环
            except httpx.HTTPStatusError as e:
                self._log.warning(f"Coze poll tick {tick} HTTP error: {e}")
            except httpx.TimeoutException:
                self._log.warning(f"Coze poll tick {tick} timed out, retrying...")
            except Exception as e:
                self._log.warning(f"Coze poll tick {tick} recoverable error: {e}")

            await asyncio.sleep(self.cfg.coze_poll_interval)

        raise TimeoutError(
            f"Coze polling exceeded "
            f"{self.cfg.coze_poll_max_ticks * self.cfg.coze_poll_interval:.0f}s without completion."
        )

    # ------------------------------------------------------------------
    # 指数退避（仅在非最后一次重试时等待）
    # ------------------------------------------------------------------
    async def _backoff(self, attempt: int) -> None:
        import asyncio
        if attempt < self.cfg.coze_submit_retries - 1:
            wait = self.cfg.coze_retry_sleep * (2 ** attempt)
            self._log.info(f"Backoff {wait:.1f}s before retry {attempt + 2}...")
            await asyncio.sleep(wait)


# ==============================================================================
# Mock Provider（所有真实 API 均不可用时的合法结构兜底）
# ==============================================================================
class MockProvider(BaseLLMProvider):
    """返回结构合法的 Mock JSON，保证下游 extract_and_validate_assets 不崩溃。"""

    async def generate_content(self, prompt: str) -> str:
        import json, logging
        logging.getLogger("services_v2.mock").warning("⚠️ MockProvider activated — no API key found.")
        return json.dumps({
            "assets": [{
                "scene_id": "MOCK_SCENE_001",
                "target_engine": "Mock",
                "narrative_analysis": {
                    "intent": "系统降级备用响应，请检查 .env 中的 API Key 配置",
                    "emotional_register": "中性"
                },
                "generative_cornerstones": {
                    "t2i_prompt": "/imagine prompt: system standby --v 6.1 --ar 16:9",
                    "i2v_prompt": "Camera static. Subject idle.",
                    "negative_prompt": "text, watermark, blurry"
                },
                "state_update": None
            }]
        }, ensure_ascii=False)


# ==============================================================================
# LLMGateway — 统一网关（策略路由 + Mock 兜底 + chat_sync 适配层）
# ==============================================================================
import asyncio
import logging
import concurrent.futures

_gw_logger = logging.getLogger("services_v2.gateway")


class LLMGateway:
    """
    统一 LLM 调用入口，替代 services.py 的 LLMService monolith。

    策略路由优先级：COZE > OPENAI > MOCK（与 services.py 保持一致）
    chat()      — 异步接口，FastAPI / asyncio 环境首选
    chat_sync() — 同步包装器，Streamlit 环境使用
    """

    def __init__(self):
        cfg = ServiceConfig()
        self._cfg = cfg

        coze_key = os.getenv("COZE_API_KEY")
        coze_bot = os.getenv("COZE_BOT_ID")
        std_key  = os.getenv("OPENAI_STD_API_KEY")   # DeepSeek / 智谱 / 任意兼容接口
        oai_key  = os.getenv("OPENAI_API_KEY")

        if coze_key and coze_bot:
            self._provider = CozeProvider(coze_key, coze_bot, cfg)
            self.mode = "COZE"
        elif std_key:
            self._provider = OpenAIStandardProvider(std_key, cfg)
            self.mode = "OPENAI_STD"
        elif oai_key:
            self._provider = OpenAIProvider(oai_key, cfg)
            self.mode = "OPENAI"
        else:
            self._provider = MockProvider()
            self.mode = "MOCK"

        _gw_logger.info(f"🤖 LLMGateway Init: Mode={self.mode}")

    # ------------------------------------------------------------------
    # 异步入口（FastAPI 路由必须 await 此方法）
    # ------------------------------------------------------------------
    async def chat(self, prompt: str) -> str:
        """
        调用 Provider。Provider 异常直接上抛，由调用方决定如何处理。
        Mock fallback 已从生产路径移除：静默降级会让真实错误完全不可见。
        """
        try:
            return await self._provider.generate_content(prompt)
        except Exception as e:
            _gw_logger.error(f"Provider [{self.mode}] failed: {e}")
            raise

    # ------------------------------------------------------------------
    # 同步入口（Streamlit / 脚本环境）
    # 逻辑与 services.py chat_sync 完全对齐，修复跨 Loop 协程传递 Bug
    # ------------------------------------------------------------------
    def chat_sync(self, prompt: str) -> str:
        try:
            asyncio.get_running_loop()
            # 已有事件循环（如误在 FastAPI 路由内调用）：在独立线程新建 loop 执行
            def _run_in_new_loop():
                return asyncio.run(self.chat(prompt))   # 协程在新线程内就地创建
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            fut = pool.submit(_run_in_new_loop)
            try:
                return fut.result(timeout=self._cfg.chat_sync_timeout)
            except concurrent.futures.TimeoutError:
                _gw_logger.error(
                    f"chat_sync timed out after {self._cfg.chat_sync_timeout}s."
                )
                fut.cancel()
                raise TimeoutError(
                    f"LLM Provider [{self.mode}] timed out after {self._cfg.chat_sync_timeout}s. "
                    "Check API connectivity or increase chat_sync_timeout."
                )
            finally:
                pool.shutdown(wait=False)   # 不等待后台线程，立即释放调用线程
        except RuntimeError:
            # 无运行中的事件循环（正常 Streamlit / 脚本场景）
            return asyncio.run(self.chat(prompt))


# ==============================================================================
# 硬件检测（与 services.py 接口兼容，供 web_ui.py 直接替换导入）
# ==============================================================================
def get_gpu_status() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            vram = torch.cuda.get_device_properties(0).total_memory / 1e9
            name = torch.cuda.get_device_name(0)
            return f"🟢 GPU Online: {name} ({vram:.1f}GB VRAM)"
        return "⚪ CPU Mode (Neural Engine Limited)"
    except ImportError:
        return "⚪ CPU Mode (torch not installed)"
    except Exception:
        return "🟢 GPU Detected (Unknown Info)"


# ==============================================================================
# 全局单例（模块加载时初始化一次，替代 services.llm_service）
# ==============================================================================
llm_service = LLMGateway()
