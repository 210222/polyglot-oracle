# -*- coding: utf-8 -*-
"""
ui_components.py - v12.1 View Components (Polyglot Oracle UI)
[Upgrade]:
    1. 注入了 'VIDEO_ENGINES' 齿轮切换器，供用户随时切换生成目标。
    2. UI 渲染深度适配，分离展示 T2I 参考图与 I2V 视频运镜提示词。
    3. 加入了“状态更迭 (State Update)”的醒目拦截展示。
"""
import streamlit as st
import json
import io
import zipfile
import time
from datetime import datetime

# 加载全局配置
try:
    from config import VISUAL_PRESETS, VIDEO_ENGINES
except ImportError:
    VISUAL_PRESETS = {"MJ_REALISM_V10": {"name": "Default"}}
    VIDEO_ENGINES = {"Kling_2_6": {"name": "Kling 2.6", "description": "Safe Mode"}}

# ==========================================================
# 💾 Ledger 持久化（零依赖，本地 JSON）
# ==========================================================
import pathlib

_LEDGER_PATH = pathlib.Path(__file__).parent / "data" / "ledger.json"


def save_ledger(ledger: dict) -> None:
    """将 Visual Ledger 持久化到 data/ledger.json，session 重启后自动恢复。"""
    try:
        _LEDGER_PATH.write_text(
            json.dumps(ledger, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        import logging
        logging.getLogger("ui_components").warning(f"Ledger 持久化写入失败: {e}")


def load_ledger() -> dict:
    """读取持久化的 Ledger 文件，文件不存在或损坏时静默返回 {}。"""
    try:
        return json.loads(_LEDGER_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ==========================================================
# 🎨 状态管理组件
# ==========================================================
def init_session_states():
    """初始化所有的页面状态变量"""
    defaults = {
        'generated_assets': [],
        'download_ready': False,
        'visual_ledger': {
            "hero_ref_url": "", 
            "physical_state": "Face smeared with engine oil, sweat dripping (满脸机油，汗水滴落)",
            "outfit": "Distressed tactical leather jacket, torn grey hoodie (做旧战术皮衣，破损卫衣)"
        },
        'pending_sync': False,
        'selected_preset': "MJ_REALISM_V10",
        'selected_engine': "Kling_2_6"  # 🔥 新增：默认引擎状态
    }
    
    _ledger_was_missing = 'visual_ledger' not in st.session_state  # 持久化恢复检测点

    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

    # 持久化 Ledger 恢复：仅在本次会话首次初始化 visual_ledger 时用磁盘状态覆盖默认值
    if _ledger_was_missing:
        saved = load_ledger()
        if saved:
            st.session_state['visual_ledger'] = saved

def sync_ledger_state():
    """当大模型触发状态变化时，强制同步刷新 UI 输入框"""
    if st.session_state.get('pending_sync', False):
        ledger = st.session_state['visual_ledger']
        # physical_state 在 Pipeline 层是 list（visual_tags_change），UI 绑定层统一转为 str
        ps = ledger.get('physical_state', '')
        st.session_state['ledger_state_input'] = ", ".join(ps) if isinstance(ps, list) else str(ps)
        st.session_state['ledger_outfit_input'] = ledger.get('outfit', '')
        st.session_state['pending_sync'] = False

# ==========================================================
# 🎛️ 左侧边栏：配置与齿轮
# ==========================================================
def render_sidebar():
    st.sidebar.markdown("### 🎬 多语神谕 (Target Engine)")
    
    # --- 1. 引擎切换齿轮 ---
    engine_options = {v['name']: k for k, v in VIDEO_ENGINES.items()}
    
    # 获取当前选中引擎的 Index
    try:
        current_index = list(engine_options.values()).index(st.session_state['selected_engine'])
    except ValueError:
        current_index = 0
        
    selected_engine_name = st.sidebar.selectbox(
        "选择目标视频引擎", 
        options=list(engine_options.keys()),
        index=current_index,
        help="The Commander 将动态编译符合该引擎语法的视频提示词"
    )
    # 保存引擎 Key (如 "Hailuo_01")
    st.session_state['selected_engine'] = engine_options[selected_engine_name]
    
    # 展示当前引擎的约束规则提示
    engine_desc = VIDEO_ENGINES[st.session_state['selected_engine']].get('description', '')
    st.sidebar.caption(f"💡 {engine_desc}")

    st.sidebar.divider()
    
    # --- 2. 视觉预设切换 ---
    st.sidebar.markdown("### 🎨 画面质感预设")
    preset_options = {v['name']: k for k, v in VISUAL_PRESETS.items()}
    try:
        preset_idx = list(preset_options.values()).index(st.session_state['selected_preset'])
    except ValueError:
        preset_idx = 0
        
    selected_preset_name = st.sidebar.selectbox(
        "Style Preset", 
        options=list(preset_options.keys()),
        index=preset_idx
    )
    st.session_state['selected_preset'] = preset_options[selected_preset_name]

    st.sidebar.divider()

    # --- 3. UE5 UDP 推送控制 ---
    st.sidebar.markdown("### 📡 UE5 Link (UDP)")
    st.session_state["ue5_enabled"] = st.sidebar.toggle(
        "推送至 UE5",
        value=st.session_state.get("ue5_enabled", False),
        help="开启后，每次 Oracle 成功生成将自动向 UE5 发送 UDP 数据包"
    )
    if st.session_state["ue5_enabled"]:
        st.session_state["ue5_port"] = st.sidebar.number_input(
            "目标端口",
            min_value=1024, max_value=65535,
            value=st.session_state.get("ue5_port", 11111),
            step=1,
            help="生产端: 11111 (ue_receiver.py) | 调试端: 11112 (ue_link_debugger.py)"
        )
        st.sidebar.caption("🟢 UE5 Link 已激活，生成完成后自动推包")
    else:
        st.sidebar.caption("⚪ UE5 Link 已关闭")

    st.sidebar.divider()

    # --- 4. 连续性视觉账本 ---
    st.sidebar.markdown("### 🎭 视觉账本 (Visual Ledger)")
    st.sidebar.caption("系统会自动追踪角色受到的物理影响，确保跨镜头连续性。")
    
    def update_ledger(key, input_key):
        st.session_state['visual_ledger'][key] = st.session_state[input_key]
        save_ledger(st.session_state['visual_ledger'])

    # [SESSION STATE FIX] 在组件渲染前预初始化 key，避免 value= 与 Session State API 双重赋值冲突
    if "ledger_state_input" not in st.session_state:
        st.session_state["ledger_state_input"] = st.session_state['visual_ledger']['physical_state']
    if "ledger_outfit_input" not in st.session_state:
        st.session_state["ledger_outfit_input"] = st.session_state['visual_ledger']['outfit']
    if "ledger_ref_input" not in st.session_state:
        st.session_state["ledger_ref_input"] = st.session_state['visual_ledger']['hero_ref_url']

    st.sidebar.text_input(
        "物理状态 (Physical State)",
        key="ledger_state_input",
        on_change=update_ledger,
        args=("physical_state", "ledger_state_input")
    )
    st.sidebar.text_input(
        "英雄服装 (Outfit)",
        key="ledger_outfit_input",
        on_change=update_ledger,
        args=("outfit", "ledger_outfit_input")
    )
    st.sidebar.text_input(
        "角色参考图 (Face URL)",
        key="ledger_ref_input",
        placeholder="Midjourney --cref URL",
        on_change=update_ledger,
        args=("hero_ref_url", "ledger_ref_input")
    )

# ==========================================================
# 🃏 渲染主结果卡片
# ==========================================================
def render_asset_card(asset, idx, api_translation=None):
    meta = asset.get('meta_data', {})
    engine_used = meta.get('engine_used', asset.get('target_engine', 'Unknown Engine'))

    st.markdown(f"#### 🎬 镜头 {idx+1} ({asset.get('scene_id', 'SC_UNKNOWN')})")
    st.caption(f"🎯 **适配引擎**: `{engine_used}` | 🧠 **知识库来源**: `{meta.get('rag_source', 'Default')}`")

    # --- 叙事分析（intent / friction_scan）---
    na = asset.get('narrative_analysis', {})
    if na:
        intent = na.get('intent', '')
        friction = na.get('friction_scan', '')
        if intent:
            st.markdown(f"> 🎯 **镜头意图**: {intent}")
        if friction:
            with st.expander("🔬 Phase 0 摩擦扫描报告", expanded=False):
                st.caption(friction)
    
    gc = asset.get('generative_cornerstones', {})
    t2i = gc.get('t2i_prompt', 'N/A')
    i2v = gc.get('i2v_prompt', 'N/A')
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**📽️ 视频生成提示词 (I2V)**")
        st.info(i2v)
    with col2:
        st.markdown("**📸 参考底图提示词 (T2I)**")
        st.success(t2i)

    neg = gc.get('negative_prompt', '')
    if neg:
        with st.expander("🚫 反向提示词 (Negative Prompt)", expanded=False):
            st.caption(neg)

    # --- edit_bridge 剪辑建议 ---
    eb = asset.get("edit_bridge")
    if eb and isinstance(eb, dict):
        cut = eb.get("cut_type", "")
        note = eb.get("transition_note", "")
        pacing = eb.get("pacing", "")
        if cut or note:
            with st.expander("✂️ 剪辑建议 (Edit Bridge)", expanded=False):
                st.caption(f"**剪辑方式**: `{cut}` | **节奏**: `{pacing}`")
                if note:
                    st.caption(note)

    # --- 拦截并展示状态的更迭 ---
    state_update = asset.get("state_update")
    if state_update and isinstance(state_update, dict):
        tags = state_update.get("visual_tags_change")
        reason = state_update.get("reason", "")
        if tags:
            st.warning(f"🔄 **Ledger 更新发生**: 系统检测到新状态 `{tags}`\n\n*({reason})*")
    st.divider()

# ==========================================================
# 📦 下载组件
# ==========================================================
def handle_download_logic():
    if not st.session_state['generated_assets']:
        return

    c1, c2 = st.columns([1, 2])
    with c1:
        if st.button("📦 编译交付包 (Compile)", use_container_width=True):
            manifest = {
                "timestamp": datetime.now().isoformat(),
                "project_meta": st.session_state['visual_ledger'],
                "assets": st.session_state['generated_assets']
            }
            mem_zip = io.BytesIO()
            with zipfile.ZipFile(mem_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
                
                prompts_txt = ""
                for i, a in enumerate(st.session_state['generated_assets']):
                    gc = a.get('generative_cornerstones', {})
                    t2i = gc.get('t2i_prompt', '')
                    i2v = gc.get('i2v_prompt', '')
                    prompts_txt += f"[{a.get('scene_id', f'SC_{i}')}]\nT2I: {t2i}\nI2V: {i2v}\n\n"
                zf.writestr("prompts.txt", prompts_txt)
                
            mem_zip.seek(0)
            st.session_state['download_payload'] = mem_zip
            st.session_state['download_ready'] = True
            st.success("Ready!")
            
    with c2:
        if st.session_state['download_ready']:
            st.download_button(
                "💾 下载 ZIP 文件",
                data=st.session_state['download_payload'],
                file_name=f"polyglot_assets_{int(time.time())}.zip",
                mime="application/zip",
                use_container_width=True
            )