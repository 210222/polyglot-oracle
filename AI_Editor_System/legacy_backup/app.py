# [DEPRECATED] 此文件已废弃，请使用 web_ui.py。
# 原因：ai_editor_inference 已从 ai_editor_core_v2 中移除；
#       完整功能（Visual Ledger、引擎选择、Polyglot Oracle）已由 web_ui.py 实现。
# 启动命令：streamlit run web_ui.py
raise DeprecationWarning(
    "app.py 已废弃，请运行 `streamlit run web_ui.py`"
)

import asyncio
import streamlit as st
from ai_editor_core_v2 import ai_editor_inference

st.title("AI编辑专家系统")
task = st.selectbox("选择任务类型", ["合规审核", "纠错", "文风转换", "选题策划"])
text = st.text_area("输入文本", height=200)
user_id = st.text_input("用户ID", "unknown_user")

if st.button("开始处理"):
    with st.spinner("AI处理中..."):
        result = asyncio.run(ai_editor_inference(text, task, user_id))
    if result.get("success"):
        st.subheader("处理结果")
        st.markdown(result.get("data", ""))
    else:
        st.error(f"处理失败: {result.get('error')}")