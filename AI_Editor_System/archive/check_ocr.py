import os
import sys
from colorama import init, Fore

init(autoreset=True)

print(f"{Fore.YELLOW}🔍 正在尝试启动 PaddleOCR 引擎...")

try:
    import cv2
    print(f"{Fore.GREEN}✅ OpenCV 导入成功 (v{cv2.__version__})")
except ImportError as e:
    print(f"{Fore.RED}❌ OpenCV 导入失败: {e}")

try:
    import shapely
    print(f"{Fore.GREEN}✅ Shapely 导入成功 (v{shapely.__version__})")
except ImportError as e:
    print(f"{Fore.RED}❌ Shapely 导入失败 (这是常见原因): {e}")

try:
    from paddleocr import PPStructure
    print(f"{Fore.GREEN}✅ PaddleOCR 库导入成功")
    
    print(f"{Fore.YELLOW}🔥 正在尝试点火 (初始化模型)...")
    # 尝试初始化，模拟 vision_core 的行为
    engine = PPStructure(show_log=False, use_gpu=False, lang='ch')
    
    if engine:
        print(f"{Fore.GREEN}🎉🎉🎉 引擎启动成功！OCR 功能已修复。")
        print(f"{Fore.CYAN}👉 现在您可以运行 python run_ingest.py 了")
    else:
        print(f"{Fore.RED}❌ 引擎初始化返回空值")

except Exception as e:
    print(f"{Fore.RED}❌ 致命错误: {e}")
    print(f"{Fore.YELLOW}💡 建议：尝试 pip install paddlepaddle paddleocr shapely opencv-contrib-python --force-reinstall")