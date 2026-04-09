# -*- coding: utf-8 -*-
"""
clean_dirty_records.py — 脏数据定向清理工具
从 ChromaDB 的 director_expert_en 集合中，按 source 字段删除非书籍记录。

运行方式：
    python clean_dirty_records.py
"""
import os
import sys

# 确保能 import config
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), override=True)

from config import DB_PATH

# 需要从 director_expert_en 删除的脏数据来源文件名
DIRTY_SOURCES = ["Midjourney.csv", "train_data.csv"]
TARGET_COLLECTION = "screenplay_expert_en"


def main():
    import chromadb
    from chromadb.utils import embedding_functions

    print(f"🔌 连接向量库：{DB_PATH}")
    client = chromadb.PersistentClient(path=DB_PATH)

    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="BAAI/bge-small-en-v1.5"
    )

    try:
        col = client.get_collection(name=TARGET_COLLECTION, embedding_function=ef)
    except Exception as e:
        print(f"❌ 无法获取集合 {TARGET_COLLECTION}: {e}")
        return

    print(f"📦 集合 {TARGET_COLLECTION} 当前共 {col.count()} 条记录")

    total_deleted = 0
    for source in DIRTY_SOURCES:
        try:
            results = col.get(
                where={"source": source},
                include=["metadatas"]
            )
            ids = results.get("ids", [])
            if not ids:
                print(f"  ⚠️  未找到 source='{source}' 的记录，跳过")
                continue

            col.delete(ids=ids)
            print(f"  ✅ 已删除 source='{source}'：{len(ids)} 条")
            total_deleted += len(ids)
        except Exception as e:
            print(f"  ❌ 删除 source='{source}' 失败: {e}")

    print(f"\n🏁 清理完成，共删除 {total_deleted} 条脏数据")
    print(f"📦 集合 {TARGET_COLLECTION} 现剩余 {col.count()} 条记录")


if __name__ == "__main__":
    main()
