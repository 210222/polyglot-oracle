import os

# 配置你的知识库路径
TARGET_DIR = r"D:\Claudedaoy\编辑系统\专家知识库"

# 支持的格式 (与主脚本保持一致)
SUPPORTED_EXTS = ('.pdf', '.txt', '.epub', '.csv')

print(f"🕵️‍♂️ [雷达启动] 正在深度扫描: {TARGET_DIR}")
print("-" * 50)

found_count = 0
ignored_count = 0

if not os.path.exists(TARGET_DIR):
    print(f"❌ 致命错误：找不到目录 {TARGET_DIR}")
    print("请检查文件夹名字是否写错！")
    exit()

for root, dirs, files in os.walk(TARGET_DIR):
    # 计算当前目录的相对深度
    level = root.replace(TARGET_DIR, '').count(os.sep)
    indent = ' ' * 4 * (level)
    print(f"{indent}📂 文件夹: {os.path.basename(root)}")
    
    sub_indent = ' ' * 4 * (level + 1)
    
    for f in files:
        f_path = os.path.join(root, f)
        ext = os.path.splitext(f)[1].lower()
        
        if ext in SUPPORTED_EXTS:
            print(f"{sub_indent}✅ [可识别] {f}")
            found_count += 1
        else:
            print(f"{sub_indent}❌ [不支持] {f} (格式: {ext})")
            ignored_count += 1

print("-" * 50)
print(f"📊 扫描报告:")
print(f"   ✅ 能够入库的文件: {found_count} 个")
print(f"   ❌ 被忽略的文件  : {ignored_count} 个")

if ignored_count > 0:
    print("\n💡 架构师建议: 系统不支持 .doc/.docx/.mobi 等格式。")
    print("   请将它们转换为 .txt 或 .pdf 后重新运行入库脚本。")