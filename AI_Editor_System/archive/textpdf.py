import os
import fitz # PyMuPDF
from colorama import init, Fore

init(autoreset=True)

# ✅ 智能模式：这里填文件夹路径或者具体文件路径都可以，脚本会自动识别
TARGET_PATH = r"D:\Claudedaoy\AI_Editor_System\Knowledge_Base\02_Director\01_Visual Language\电影语言的语法（插图修订版） (丹尼艾尔·阿里洪(Daniel Arijon)) (Z-Library).pdf"

def diagnose_pdf(file_path):
    print(f"\n{Fore.CYAN}🩺 [开始诊断]: {os.path.basename(file_path)}")
    print(f"   📍 完整路径: {file_path}")
    
    try:
        doc = fitz.open(file_path)
    except Exception as e:
        print(f"{Fore.RED}❌ 致命错误：无法打开 PDF。原因: {e}")
        return

    # 1. 检查加密
    if doc.is_encrypted:
        print(f"{Fore.RED}🔒 状态：文件已加密 (加密标准: {doc.metadata.get('encryption', 'Unknown')})")
        print(f"{Fore.YELLOW}💡 解决方案：请用 Chrome 打开此文件 -> 打印 -> 另存为 PDF，即可清除密码。")
    else:
        print(f"{Fore.GREEN}✅ 状态：文件未加密")

    # 2. 检查页数
    page_count = len(doc)
    print(f"📄 页数: {page_count}")
    if page_count == 0:
        print(f"{Fore.RED}❌ 警告：这是个空文件")
        return

    # 3. 尝试提取文本
    try:
        text_sample = ""
        # 尝试读前3页，避免第1页是大图导致的误判
        for i in range(min(3, page_count)):
            text_sample += doc[i].get_text()
        
        print(f"📝 前3页文本量: {len(text_sample)} 字符")
        if len(text_sample) < 50:
            print(f"{Fore.YELLOW}⚠️ 提示：文本极少，这极大概率是一个【纯图片扫描版 PDF】")
            print(f"   (入库时会触发 OCR 引擎进行视觉识别，速度较慢但能处理)")
        else:
            print(f"{Fore.GREEN}✅ 文本层正常 (可直接提取)")
    except Exception as e:
        print(f"{Fore.RED}❌ 文本提取失败: {e}")

    # 4. 尝试渲染图片
    try:
        pix = doc[0].get_pixmap()
        print(f"{Fore.GREEN}✅ 图片引擎正常 (OCR可以工作)")
    except Exception as e:
        print(f"{Fore.RED}❌ 图片渲染失败: {e}")
        print(f"{Fore.RED}   这说明 PDF 内部数据流损坏，必须用浏览器打印修复！")

if __name__ == "__main__":
    # 去除可能存在的引号
    target = TARGET_PATH.strip('"').strip("'")
    
    print(f"{Fore.YELLOW}🔍 正在扫描目标: {target}")
    
    if not os.path.exists(target):
        print(f"{Fore.RED}❌ 错误：路径不存在！请检查拼写。")
    
    # 🌟 智能分支 A：如果用户给的是具体文件
    elif os.path.isfile(target):
        print(f"{Fore.MAGENTA}📂 识别模式: 单文件深度诊断")
        diagnose_pdf(target)
        
    # 🌟 智能分支 B：如果用户给的是文件夹
    elif os.path.isdir(target):
        print(f"{Fore.MAGENTA}📂 识别模式: 文件夹批量扫描 (含子目录)")
        found_count = 0
        keywords = ["电影摄影", "Framed Ink", "色彩与光线", "电影语言"] # 关键词
        
        # 使用 os.walk 支持递归扫描子文件夹
        for root, dirs, files in os.walk(target):
            for f in files:
                if not f.lower().endswith(".pdf"): continue
                
                if any(k in f for k in keywords):
                    found_count += 1
                    full_path = os.path.join(root, f)
                    diagnose_pdf(full_path)
        
        if found_count == 0:
            print(f"{Fore.RED}❌ 未找到目标文件。")
    else:
        print(f"{Fore.RED}❌ 未知路径类型")