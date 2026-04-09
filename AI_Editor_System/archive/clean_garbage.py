import os

# 你的知识库路径
KNOWLEDGE_BASE_DIR = r"D:\Claudedaoy\编辑系统\专家知识库"

def clean_garbage_files():
    print(f"🧹 开始大扫除：{KNOWLEDGE_BASE_DIR} ...\n")
    deleted_count = 0
    
    for root, dirs, files in os.walk(KNOWLEDGE_BASE_DIR):
        for file in files:
            file_path = os.path.join(root, file)
            
            # 1. 检测文件大小 (如果是 0KB 或 小于 100字节，直接判定为垃圾)
            try:
                file_size = os.path.getsize(file_path)
                if file_size < 100:  # 小于 100 字节的文件肯定是坏的
                    print(f"🗑️ 发现空文件/垃圾文件 (大小: {file_size}B): {file}")
                    os.remove(file_path) # 删除
                    deleted_count += 1
                    continue
            except Exception as e:
                print(f"⚠️ 无法访问文件: {file}")

    print(f"\n🎉 大扫除完成！共删除了 {deleted_count} 个垃圾文件。")
    print("👉 剩下的都是健康文件，请重新运行 ingest_pro_books.py")

if __name__ == "__main__":
    clean_garbage_files()