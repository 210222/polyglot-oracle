import os
import chromadb
from ingest_engine.config.settings import settings

def verify_book_in_db():
    print("==================================================")
    print(" 🕵️ ChromaDB 终极数据探针 (Database Probe) - 交互雷达版")
    print("==================================================")
    
    db_path = settings.db.chroma_persist_dir
    print(f"🔌 正在直连物理数据库: {db_path}")
    
    if not os.path.exists(db_path):
        print("❌ 数据库文件夹不存在！请确认已执行入库管线。")
        return

    client = chromadb.PersistentClient(path=db_path)
    
    collections = client.list_collections()
    if not collections:
        print("⚠️ 数据库是空的，没有任何集合房间！")
        return

    # 1. 扫描所有房间，提取所有独立书名 (基因代号)
    all_books = set()
    for col in collections:
        col_name = col.name if hasattr(col, 'name') else col
        col_obj = client.get_collection(col_name)
        data = col_obj.get(include=["metadatas"])
        if data and data.get("metadatas"):
            for meta in data["metadatas"]:
                if meta and "source" in meta:
                    all_books.add(meta["source"])
                    
    if not all_books:
        print("⚠️ 数据库房间存在，但里面没有找到任何有效数据记录！")
        return

    # 将集合转为排序列表，方便生成稳定编号
    books_list = sorted(list(all_books))
    
    print("\n📚 当前金库中已存入的知识母体列表:")
    for idx, b in enumerate(books_list, 1):
        print(f"  [{idx}] {b}")

    # 2. 交互式选择终端
    print("\n" + "-"*50)
    user_input = input("👉 请输入你要透视的【书籍编号】(如 1) 或【书名关键词】:\n> ").strip()
    
    if not user_input:
        print("❌ 未输入任何内容，探测中止。")
        return

    target_book = None
    
    # 智能判断：如果纯输入数字，则按编号索引；否则按关键词模糊匹配
    if user_input.isdigit():
        idx = int(user_input)
        if 1 <= idx <= len(books_list):
            target_book = books_list[idx - 1]
        else:
            print(f"❌ 编号 {idx} 超出范围！")
            return
    else:
        for b in books_list:
            if user_input.lower() in b.lower():
                target_book = b
                break
                
    if not target_book:
        print(f"\n❌ 找遍了所有房间，没有找到匹配 '{user_input}' 的书籍！")
        return

    print(f"\n🎯 成功锁定目标书籍基因: {target_book}")
    
    # 3. 跨房间提取该书的所有切块
    target_docs = []
    target_metas = []
    target_room = ""
    
    for col in collections:
        col_name = col.name if hasattr(col, 'name') else col
        col_obj = client.get_collection(col_name)
        results = col_obj.get(
            where={"source": target_book},
            include=["documents", "metadatas"]
        )
        if results["documents"]:
            target_docs.extend(results["documents"])
            target_metas.extend(results["metadatas"])
            target_room = col_name
            # 通常一本书只会在一个语言专家房里，找到即可
            
    total_chunks = len(target_docs)
    if total_chunks == 0:
        print("⚠️ 找到了书名记录，但没有正文数据 (异常)！")
        return
        
    # 🚀 核心逻辑：按原始的物理拆片 (file_path) 和切块索引 (chunk_index) 重新排序！
    combined = list(zip(target_docs, target_metas))
    # 优先按文件路径排，其次按 chunk_index 排，确保 100% 还原原文顺序
    combined.sort(key=lambda x: (x[1].get('file_path', ''), x[1].get('chunk_index', 0)))
    
    sorted_docs = [x[0] for x in combined]
    sorted_metas = [x[1] for x in combined]

    # 4. 分析 VLM 标签与拆分来源
    vlm_chunk_count = 0
    total_vlm_tags = 0
    part_sources = set()
    
    for doc in sorted_docs:
        tags = doc.count("🖼️") + doc.count("[AI 导演视觉解析]") + doc.count("[AI_VISION_TARGET")
        if tags > 0:
            vlm_chunk_count += 1
            total_vlm_tags += tags
            
    for meta in sorted_metas:
        file_path = meta.get('file_path', '')
        if file_path:
            part_sources.add(os.path.basename(file_path))
        
    print("\n" + "="*50)
    print(" 📊 知识体检报告 (Autopsy Report)")
    print("="*50)
    print(f"📦 [容量检定]: 成功提取 {total_chunks} 个独立语义块 (Chunks)")
    print(f"🗂️ [物理存放]: 落户于专家集合 -> {target_room}")
    
    print(f"\n🧩 [无缝缝合验证]: 数据库中的数据来源于以下 {len(part_sources)} 个物理文件:")
    for p in sorted(list(part_sources)):
        print(f"   ✅ {p}")
        
    sample_meta = sorted_metas[0]
    print(f"\n🏷️ [专家路牌]: {sample_meta.get('kb_category', 'Unknown')}")
    print(f"🌐 [语言雷达]: {sample_meta.get('language', 'Unknown')}")
    print(f"👁️‍🗨️ [多模态融合]: 发现 {total_vlm_tags} 处视觉/特殊解析标记！")
    
    # 5. X 光反向导出
    export_dir = os.path.join(os.getcwd(), "pipeline_output")
    os.makedirs(export_dir, exist_ok=True)
    safe_name = "".join([c for c in target_book if c.isalnum() or c in [' ', '_', '-']]).strip()
    export_path = os.path.join(export_dir, f"XRay_{safe_name[:30]}.md")
    
    with open(export_path, "w", encoding="utf-8") as f:
        f.write(f"# 📚 数据库底层 X光透视报告\n")
        f.write(f"- **目标书籍**: {target_book}\n")
        f.write(f"- **总切块数**: {total_chunks}\n")
        f.write(f"- **视觉插图**: {total_vlm_tags} 张\n\n---\n\n")
        
        for i, (doc, meta) in enumerate(zip(sorted_docs, sorted_metas)):
            source_file = os.path.basename(meta.get('file_path',''))
            chunk_idx = meta.get('chunk_index', i)
            
            f.write(f"### 🧩 Chunk [{i+1}/{total_chunks}] (物理索引: {chunk_idx} | 来源: {source_file})\n")
            if "🖼️" in doc or "AI 导演视觉解析" in doc:
                f.write("> 💡 **[探针提示]**: 此区块包含 AI 多模态视觉解析！\n\n")
            f.write(f"{doc}\n\n---\n\n")
            
    print("\n" + "-"*50)
    print(" 📖 [首部探针] (验证数据的开头):")
    print(f"  > {sorted_docs[0][:150].replace(chr(10), ' ')}...")
    print("\n 📖 [尾部探针] (验证数据的结尾):")
    print(f"  > ...{sorted_docs[-1][-150:].replace(chr(10), ' ')}")
    print("-"*50 + "\n")
    
    print(f"✅ X光逆向导出成功！")
    print(f"👉 报告已生成至: {export_path}")

if __name__ == "__main__":
    # 去掉了死板的硬编码，直接调用！
    verify_book_in_db()