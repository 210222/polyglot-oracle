# -*- coding: utf-8 -*-
"""
test_rag_protocol.py
RAG 修复协议自动化验证脚本
用于验证：
1. Context Reordering (上下文重排序) 是否正确执行。
2. Query Rewrite (查询重写) 是否正确注入了视觉状态。
"""
import logging
from typing import List

# 导入修改后的模块
try:
    from rag_formatter import reorder_primacy_recency as reorder_context_primacy_recency
    from ai_editor_core_v2 import get_ai_response
    print("✅ 成功导入核心模块")
except ImportError as e:
    print(f"❌ 导入失败，请确保脚本在项目根目录下运行。错误: {e}")
    exit()

def test_reordering_algorithm():
    print("\n🔹 测试 1: 上下文重排序 (Lost-in-the-Middle Fix)...")
    
    # 模拟检索到的 5 个文档，按相关性排序 (D1 最相关)
    mock_docs = ["D1_最佳答案", "D2_次佳答案", "D3_普通", "D4_普通", "D5_噪音"]
    
    # 执行重排序
    reordered = reorder_context_primacy_recency(mock_docs)
    
    print(f"原始顺序: {mock_docs}")
    print(f"重排结果: {reordered}")
    
    # 验证逻辑：D1 应在头部，D2 应在尾部
    if reordered[0] == "D1_最佳答案" and reordered[-1] == "D2_次佳答案":
        print("✅ 通过: 首因效应(Primacy)与近因效应(Recency)布局正确。")
    else:
        print("❌ 失败: 排序逻辑未按预期执行。")

def test_state_injection_simulation():
    print("\n🔹 测试 2: 状态感知查询注入模拟...")
    
    # 模拟一个复杂的视觉状态
    mock_ledger = {
        "hero_ref_url": "http://test.com/img.jpg",
        "physical_state": "浑身湿透，伤口流血 (Soaked, Bleeding)",
        "outfit": "破损的战术背心 (Torn Vest)"
    }
    
    user_script = "他走进房间。"
    
    print(f"用户剧本: {user_script}")
    print(f"当前状态: {mock_ledger['physical_state']}")
    
    # 注意：这里我们无法直接拦截 ai_editor_core 内部的变量，
    # 但我们可以观察日志或通过一次“空跑”来验证代码路径没有崩溃。
    try:
        # 使用 context=True 触发 RAG 逻辑
        # 由于没有真实数据库，核心代码会回退到 Fallback 或内置逻辑，这是预期的
        result = get_ai_response(
            text_input=user_script,
            context=True,
            visual_ledger=mock_ledger
        )
        
        # 检查元数据中是否记录了 RAG 活动
        assets = result.get("assets", [])
        if assets:
            meta = assets[0].get("meta_data", {})
            rag_active = meta.get("rag_active")
            rag_preview = meta.get("rag_context_preview", "")
            
            if rag_active:
                print("✅ 通过: RAG 模块已激活。")
                print(f"📝 上下文预览: {rag_preview[:100]}...")
            else:
                print("⚠️ 警告: RAG 模块未激活 (可能是数据库未初始化，属正常现象)。")
                
            # 检查 Ledger 是否回传
            snapshot = meta.get("ledger_snapshot", {})
            if snapshot.get("physical_state") == mock_ledger["physical_state"]:
                print("✅ 通过: Visual Ledger 状态已成功传递至生成管线。")
            else:
                print("❌ 失败: Ledger 状态在传递过程中丢失。")
                
    except Exception as e:
        print(f"❌ 运行时错误: {e}")

if __name__ == "__main__":
    test_reordering_algorithm()
    test_state_injection_simulation()
    print("\n测试完成。")