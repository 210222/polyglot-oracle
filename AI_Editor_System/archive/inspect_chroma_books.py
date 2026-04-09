import chromadb
import os
from collections import Counter

def inspect_chroma_db(db_path):
    # 1. 检查路径是否存在
    if not os.path.exists(db_path):
        print(f"❌ 错误：路径不存在 -> {db_path}")
        return

    print(f"📂 正在连接数据库: {db_path} ...")
    
    try:
        # 2. 连接持久化客户端
        client = chromadb.PersistentClient(path=db_path)
        
        # 3. 获取所有集合
        collections = client.list_collections()
        if not collections:
            print("⚠️ 警告：数据库中没有发现任何集合 (Collections)。")
            return

        print(f"✅ 连接成功，发现 {len(collections)} 个集合。")
        print("="*60)

        # 4. 遍历每个集合查看内容
        for col in collections:
            print(f"📚 集合名称: [ {col.name} ]")
            
            # 获取该集合中所有数据的 metadata（不加载向量，速度较快）
            # limit=None 表示获取全部，如果数据量巨大(百万级)，建议设置 limit=10000 先预览
            data = col.get(include=['metadatas'])
            metadatas = data.get('metadatas', [])
            
            count = len(metadatas)
            print(f"   📊切片总数: {count}")

            if count == 0:
                print("   (空集合)")
                print("-" * 60)
                continue

            # 5. 智能分析：尝试寻找代表“书名”的字段
            # 通常是 'source', 'title', 'filename', 或 'book_name'
            book_sources = []
            
            # 这里的 keys 是为了看看你用了什么字段存书名
            sample_keys = metadatas[0].keys() if metadatas else []
            print(f"   🔑 元数据字段: {list(sample_keys)}")

            for meta in metadatas:
                # 优先查找以下字段作为书名标识
                book_name = (
                    meta.get('title') or 
                    meta.get('source') or 
                    meta.get('filename') or 
                    meta.get('book') or 
                    "未知来源"
                )
                # 可选：去掉路径，只保留文件名（更整洁）
                if isinstance(book_name, str) and "\\" in book_name:
                    book_name = os.path.basename(book_name)
                    
                book_sources.append(book_name)

            # 6. 统计去重
            book_counts = Counter(book_sources)
            
            print("   📖 包含书籍清单 (书名 | 切片数量):")
            for book, num in book_counts.most_common():
                print(f"      - {book:<50} : {num} 个切片")
            
            print("-" * 60)

    except Exception as e:
        print(f"❌ 读取数据库时发生错误: {e}")
        print("建议检查：ChromaDB 版本是否匹配，或路径是否被其他程序占用。")

if __name__ == "__main__":
    # 使用原始字符串 r"" 避免 Windows 路径转义问题
    target_path = r"D:\Claudedaoy\编辑系统\ai_editor_chroma_db_v9"
    inspect_chroma_db(target_path)