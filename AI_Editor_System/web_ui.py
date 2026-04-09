# -*- coding: utf-8 -*-
"""
web_ui.py - v12.2 Main Controller (Async-Compatible Edition)
[Refactor]:
    1. [ASYNC FIX] 引入 asyncio，使用 asyncio.run() 在 Streamlit 同步环境中
       安全驱动 async def get_ai_response()，不阻塞也不引发事件循环冲突。
    2. [ENGINE FIX] 调用 get_ai_response 时同时传入 target_engine_key 和
       target_engine（引擎显示名），确保 V11 Prompt 的 [TARGET ENGINE] 精确触发。
    3. 页面 UI 布局、Ledger 同步、下载逻辑完全不变。
"""
import asyncio
import streamlit as st
import time

# --- 双重保险加载环境变量 ---
from dotenv import load_dotenv
load_dotenv()

from ui_components import (
    init_session_states,
    sync_ledger_state,
    render_sidebar,
    render_asset_card,
    handle_download_logic,
    save_ledger,
)

try:
    from config import VIDEO_ENGINES, VISUAL_PRESETS
    from ai_editor_core_v2 import get_ai_response, get_rag_health
    from hardware import get_gpu_status
    from ue_bridge import send_assets_to_ue5
    from rag_retriever import query_rag
    CORE_AVAILABLE = True
except ImportError as e:
    CORE_AVAILABLE = False
    if 'VISUAL_PRESETS' not in locals(): VISUAL_PRESETS = {"默认模式": {"name": "安全模式"}}
    if 'VIDEO_ENGINES' not in locals(): VIDEO_ENGINES = {"Kling_2_6": {"name": "Kling 2.6"}}

    def get_gpu_status(): return f"核心离线: {str(e)}"
    def get_rag_health(): return f"🔴 RAG 离线: 核心模块加载失败"
    def send_assets_to_ue5(assets, **kwargs): return (0, [f"核心离线，UE5 发送跳过"])
    def query_rag(text, top_k=3): return ""
    # 降级为同步 Mock，签名与真实函数保持一致
    async def get_ai_response(**kwargs): return {"success": False, "error": f"核心服务连接失败: {str(e)}"}


# ==========================================================
# 🔧 异步调用适配器
# ==========================================================
def run_async(coro):
    """
    在 Streamlit 同步环境中安全运行 async 协程，兼容全部 Streamlit 版本。

    Streamlit < 1.18  : 渲染线程无事件循环 → asyncio.run() 直接运行（快路径）。
    Streamlit >= 1.18 : 某些渲染线程已有运行中的事件循环 → asyncio.run() 抛
                        RuntimeError: This event loop is already running。

    修复策略：检测到 running loop 时，将协程投入独立线程的新 loop 执行。
    注意：coro 在传入前已被创建（get_ai_response(...)），但尚未启动，
    未绑定任何 loop，可安全跨线程交给 asyncio.run()。

    loop.run_until_complete() 不是正确替代：它在已运行的 loop 上同样抛异常。
    """
    import concurrent.futures
    try:
        asyncio.get_running_loop()
        # 已有 loop（Streamlit >= 1.18 场景）：新线程新 loop，协程就地创建
        # 不使用 with 上下文管理器：with 的 __exit__ 调用 shutdown(wait=True)，
        # 会在 timeout 后继续阻塞直到后台协程真正结束（最长 660s）。
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        fut = pool.submit(asyncio.run, coro)
        try:
            return fut.result(timeout=150)
        except concurrent.futures.TimeoutError:
            fut.cancel()
            return {"success": False, "error": "run_async: coroutine timed out (150s)"}
        finally:
            pool.shutdown(wait=False)   # 不等待后台线程，立即释放渲染线程
    except RuntimeError:
        # 无 loop（正常 Streamlit 场景）：直接运行
        return asyncio.run(coro)


# ==========================================================
# 🎮 主程序入口
# ==========================================================
def main():
    st.set_page_config(page_title="Polyglot Oracle - AI Editor", layout="wide", page_icon="🎬")

    # 1. 初始化并同步状态
    init_session_states()
    sync_ledger_state()

    # 2. 顶部面板
    st.title("🎬 跨平台生成视频编排 - Polyglot Oracle")
    st.caption(f"⚙️ 系统底层: {get_gpu_status()} | 📚 知识库: {get_rag_health()}")

    # 3. 渲染左侧控制台 (会向 Session 写入 selected_engine)
    render_sidebar()

    if not CORE_AVAILABLE:
        st.error("⚠️ 核心组件加载失败，请检查 (ai_editor_core_v2, config, services_v2) 等文件依赖。")
        return

    # 4. 主交互区
    st.markdown("### 📝 线性剧本 (User Script)")
    user_script = st.text_area(
        "输入剧情描述或动作细节...",
        height=150,
        placeholder="示例：镜头跟随主角在赛博朋克小巷中奔跑，他不小心摔在水坑里，划破了西装，满脸惊恐地回头看去..."
    )

    if st.button("🚀 呼叫神谕 (Execute Oracle)", type="primary"):
        if not user_script.strip():
            st.warning("请先输入剧本！")
            return

        selected_engine_key = st.session_state['selected_engine']
        current_engine_name = VIDEO_ENGINES.get(selected_engine_key, {}).get('name', 'Kling 2.6')

        with st.spinner(f"正在编译神谕协议... [目标挂载: {current_engine_name}]"):
            rag_context = query_rag(user_script)
            response = run_async(get_ai_response(
                text=user_script,
                visual_ledger=st.session_state['visual_ledger'],
                target_engine_key=selected_engine_key,
                target_engine=current_engine_name,
                style_preset=st.session_state['selected_preset'],
                rag_context=rag_context,
                is_fallback=(rag_context == "")
            ))
        # [REACT FIX] spinner with 块退出后再写 state / toast / rerun，
        # 避免 spinner DOM 节点未卸载时触发重绘导致 removeChild 崩溃。
        if response.get("success"):
            assets = response.get("assets", [])

            # --- AI 状态追踪与 Ledger 自动同步（使用 Pipeline 返回的完整 new_ledger）---
            new_ledger = response.get("new_ledger")
            if new_ledger and isinstance(new_ledger, dict):
                st.session_state['visual_ledger'] = new_ledger
                save_ledger(new_ledger)
                st.session_state['pending_sync'] = True
                # 取最后一条 asset 的 reason 用于 toast 提示
                last_reason = ""
                if assets:
                    su = assets[-1].get("state_update") or {}
                    last_reason = su.get("reason", "")
                st.toast(f"Ledger 已全量同步 (physical + outfit): {last_reason or '状态更新'}", icon="🔄")

            # --- UDP 发送至 UE5 ---
            if st.session_state.get("ue5_enabled", False) and assets:
                ue_port = st.session_state.get("ue5_port", 11111)
                sent, errors = send_assets_to_ue5(assets, port=ue_port)
                if errors:
                    st.toast(f"UE5 发送部分失败 ({len(errors)}/{len(assets)}): {errors[0]}", icon="⚠️")
                else:
                    st.toast(f"已向 UE5 推送 {sent} 个镜头包 → 127.0.0.1:{ue_port}", icon="📡")

            st.session_state['generated_assets'] = assets
            st.session_state['download_ready'] = False
            st.rerun()
        else:
            st.error(f"神谕解析失败: {response.get('error')}")

    # 5. 结果展示区
    if st.session_state['generated_assets']:
        st.divider()
        st.subheader("📦 生产资产概览 (Assets Ledger)")
        for idx, asset in enumerate(st.session_state['generated_assets']):
            render_asset_card(asset, idx)

        # 6. 打包下载
        handle_download_logic()


if __name__ == "__main__":
    main()
