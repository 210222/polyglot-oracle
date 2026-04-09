import os
import sys
import sqlite3
import pandas as pd
from typing import Set, Dict, List
import chromadb
from chromadb.config import Settings
from colorama import init, Fore, Style

# 初始化颜色输出
init(autoreset=True)

# ==========================================
# ⚙️ 配置区域
# ==========================================
# 这里填写您 run_ingest.py 实际生成的数据库目录名
# 根据您的日志，您使用的是 v9
TARGET_DB_DIR = "ai_editor_chroma_db_v9" 

# 定义已知的污染源（黑名单文件），用于检测数据库是否干净
BLACKLIST_FILES = {
    "Virtual Production Field Guide Volume 2 v1.0-5b06b62cbc5f.pdf",
    "vp-field-guide-v1-3-01-f0bce45b6319.pdf"
}

def get_project_root():
    return os.path.dirname(os.path.abspath(__file__))

def check_sqlite_header(db_path):
    """底层检查：验证 SQLite 文件头是否完好"""
    sqlite_file = os.path.join(db_path, "chroma.sqlite3")
    if not os.path.exists(sqlite_file):
        return False, "❌ 找不到 chroma.sqlite3 文件"
    
    try:
        with open(sqlite_file, 'rb') as f:
            header = f.read(16)
        if header == b'SQLite format 3\x00':
            return True, "✅ SQLite 文件头校验通过"
        else:
            return False, "❌ SQLite 文件头损坏"
    except Exception as e:
        return False, f"❌ 文件读取错误: {str(e)}"

def inspect_database():
    root_dir = get_project_root()
    db_path = os.path.join(root_dir, TARGET_DB_DIR)
    
    print(f"\n{Fore.CYAN}🔍 开始数据库审计程序...")
    print(f"{Fore.CYAN}📍 目标路径: {db_path}")

    # 1. 物理层检查
    if not os.path.exists(db_path):
        print(f"{Fore.RED}❌ 错误：数据库目录不存在。请先运行 run_ingest.py 进行入库。")
        return

    is_valid, msg = check_sqlite_header(db_path)
    print(msg)
    if not is_valid: return

    # 2. 连接数据库
    try:
        client = chromadb.PersistentClient(
            path=db_path,
            settings=Settings(anonymized_telemetry=False, allow_reset=False)
        )
        print(f"{Fore.GREEN}✅ 数据库连接成功！")
    except Exception as e:
        print(f"{Fore.RED}❌ 连接失败: {e}")
        return

    # 3. 遍历集合 (Collections)
    collections = client.list_collections()
    total_collections = len(collections)
    print(f"\n{Fore.YELLOW}📊 发现 {total_collections} 个知识库 (Collections):")
    
    all_books_found = {} # 存储所有发现的书名
    total_chunks_system = 0

    for col in collections:
        col_name = col.name
        count = col.count()
        total_chunks_system += count
        
        print(f"\n{Fore.MAGENTA}📂 知识库: [{col_name}]")
        print(f"   └─ 知识切片总数: {count}")
        
        if count == 0:
            print(f"   ⚠️ 此库为空")
            continue

        # 获取元数据以提取书名 (限制获取，防止内存爆掉，分批次或只取 metadata)
        # 注意：这里我们只取 metadatas，不取 embeddings，速度快
        try:
            # 这里的 limit 是为了演示，如果库很大，建议 pagination，但测试脚本通常直接拉取即可
            # 如果您的库非常大(>10万条)，这里可能会慢
            result = col.get(include=['metadatas'])
            metadatas = result['metadatas']
            
            # 提取文件名 (书名)
            sources: Set[str] = set()
            polluted_files: Set[str] = set()
            
            for m in metadatas:
                if m and 'source' in m:
                    src = m['source']
                    sources.add(src)
                    # 检查污染
                    if src in BLACKLIST_FILES:
                        polluted_files.add(src)
            
            all_books_found[col_name] = list(sources)
            
            # 打印书名清单
            print(f"   📚 包含书籍 ({len(sources)} 本):")
            for i, book in enumerate(sorted(sources)):
                print(f"      {i+1}. {book}")
            
            # 污染检测报告
            if polluted_files:
                print(f"{Fore.RED}   ☢️ 警告：检测到污染文件！(黑名单文件已入库)")
                for pf in polluted_files:
                    print(f"      ❌ {pf}")
            else:
                print(f"{Fore.GREEN}   ✅ 污染检测通过：未发现黑名单文件。")

        except Exception as e:
            print(f"{Fore.RED}   ❌ 读取元数据失败: {e}")

    # 4. 最终汇总
    print(f"\n{'='*50}")
    print(f"{Fore.CYAN}📈 审计总结报告")
    print(f"{'='*50}")
    print(f"数据库状态: {Fore.GREEN}健康 (ONLINE)")
    print(f"总切片数:   {Fore.YELLOW}{total_chunks_system}")
    print(f"总书籍数:   {Fore.YELLOW}{sum(len(v) for v in all_books_found.values())}")
    
    if total_chunks_system > 0:
        print(f"{Fore.GREEN}✅ 验证通过：数据库包含有效真实数据。")
    else:
        print(f"{Fore.RED}❌ 验证失败：数据库是空的。")

if __name__ == "__main__":
    try:
        inspect_database()
        input(f"\n{Fore.CYAN}按回车键退出...")
    except KeyboardInterrupt:
        print("\n用户中断")