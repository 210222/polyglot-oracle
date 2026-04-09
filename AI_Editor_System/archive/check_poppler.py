import shutil
import os
import sys

def check_poppler():
    print("="*40)
    print("🔍 Poppler 渲染引擎探测器")
    print("="*40)

    # 1. 检查系统 PATH 中是否有 pdftoppm
    poppler_path = shutil.which("pdftoppm")
    
    if poppler_path:
        print(f"✅ 成功发现 Poppler!")
        print(f"📍 路径: {poppler_path}")
        print("-" * 40)
        print("🎉 你的双轨架构现在可以处理扫描 PDF 了。")
        return True
    else:
        print("❌ 未找到 Poppler。")
        print("-" * 40)
        print("原因分析:")
        print("1. 你可能还没有下载 Poppler (Windows 版)。")
        print("2. 你下载了，但没有把 'bin' 文件夹加到系统 PATH 环境变量中。")
        print("3. 你加了环境变量，但没有重启 VSCode/终端。")
        print("-" * 40)
        print("当前 PATH 变量 (部分):")
        for p in os.environ['PATH'].split(';')[:5]:
            print(f" - {p}")
        return False

if __name__ == "__main__":
    check_poppler()