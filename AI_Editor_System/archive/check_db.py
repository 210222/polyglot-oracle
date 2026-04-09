import os
import sys
from collections import defaultdict

# ==========================================
# 🚀 环境变量配置 (防止报错)
# ==========================================
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY_ENABLED"] = "false"
os.environ["CHROMA_SERVER_NO_INTERACTIVE_AUTH"] = "True"

import chromadb
from chromadb.config import Settings

# 🔥 暴力补丁：屏蔽 posthog
try:
    import posthog
    posthog.capture = lambda *args, **kwargs: None
    posthog.disabled = True
except ImportError:
    pass

# 配置路径
SYSTEM_ROOT = r"D:\Claudedaoy\编辑系统"
DB_ROOT_DIR = os.path.join(SYSTEM_ROOT, "ai_editor_chroma_db_v9")

def check_database_deep_scan():
    print(f"🕵️‍♂️ 正在执行 v8.6 深度审计...")
    print(f"📂 数据库路径: {DB_ROOT_DIR}")
    print("=" * 70)

    if not os.path.exists(DB_ROOT_DIR):
        print(f"❌ 错误: 数据库不存在。请先运行 ingest_pro_books.py")
        return

    try:
        # 连接数据库
        client = chromadb.PersistentClient(
            path=DB_ROOT_DIR,
            settings=Settings(anonymized_telemetry=False)
        )
        
        collections = client.list_collections()
        if not collections:
            print("⚠️ 数据库为空。")
            return

        total_files = 0
        
        # 预定义映射关系，方便您核对
        MAPPING = {
            "screenplay_expert": "对应物理文件夹: [01_编剧与故事]",
            "director_expert":   "对应物理文件夹: [02_导演与视觉]",
            "shared_common":     "对应物理文件夹: [03_法规与通识]"
        }

        for col in collections:
            count = col.count()
            
            # 获取显示名称
            folder_hint = MAPPING.get(col.name, "未知分类")
            print(f"\n🧠 知识库集合: [{col.name}]")
            print(f"   ↳ {folder_hint}")
            print(f"   ↳ 知识切片总量: {count}")
            print("-" * 70)
            
            if count == 0:
                print("   (空)")
                continue

            # 获取所有元数据
            data = col.get(include=["metadatas"])
            metas = data["metadatas"]
            
            # 统计分析
            file_stats = defaultdict(int)
            file_types = {}
            last_ingest = "未知"

            for m in metas:
                if not m: continue
                src = m.get("source", "Unknown_File")
                file_stats[src] += 1
                
                # 记录文件类型
                if src.endswith('.csv'): file_types[src] = "💎 结构表"
                elif src.endswith('.json'): file_types[src] = "⚙️ 引擎配置"
                elif src.endswith('.pdf'): file_types[src] = "📚 PDF书籍"
                elif src.endswith('.md'): file_types[src] = "📝 Markdown"
                else: file_types[src] = "📄 文本"

                # 记录最新时间
                if 'ingest_time' in m:
                    t = m['ingest_time']
                    if t > last_ingest: last_ingest = t

            # 排序输出
            sorted_files = sorted(file_stats.items(), key=lambda x: x[1], reverse=True)
            
            print(f"   {'文件名 (Source)':<45} | {'切片数':<8} | {'类型'}")
            print("   " + "." * 65)
            
            for fname, fcount in sorted_files:
                ftype = file_types.get(fname, "📄")
                # 截断长文件名
                display_name = (fname[:42] + '..') if len(fname) > 42 else fname
                print(f"   {display_name:<45} | {fcount:<8} | {ftype}")
            
            total_files += len(file_stats)
            print(f"\n   ⏱️ 最近入库时间: {last_ingest}")
            print("=" * 70)

        print(f"\n🎉 审计结束。全库共收录 {total_files} 个文件。")
        print("💡 提示: 请确认 '文件名' 是否出现在了正确的 '大脑分区' 中。")

    except Exception as e:
        print(f"❌ 读取失败: {e}")
        print("💡 可能是文件被占用，请关闭 web_ui.py 后重试。")

if __name__ == "__main__":
    check_database_deep_scan()