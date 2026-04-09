import os
import sys
import gc
import time
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
 
# === 配置区 ===
# 每处理多少页进行一次磁盘写入（内存安全的关键）
# 16GB 内存建议设为 20-30，数值越小内存越安全
CHUNK_SIZE = 20 
# 并发线程数
MAX_WORKERS = 4 
 
def check_dependencies():
    missing = []
    try: import pytesseract
    except ImportError: missing.append("pytesseract")
    try: from pdf2image import convert_from_path
    except ImportError: missing.append("pdf2image")
    try: from PIL import Image
    except ImportError: missing.append("pillow")
    try: import pypdf
    except ImportError: missing.append("pypdf")
 
    if missing:
        print("❌ 缺少必要的 Python 库：")
        print(f"pip install {' '.join(missing)}")
        return False
        
    tessdata_dir = r'C:\Program Files\Tesseract-OCR\tessdata'
    chi_sim_path = os.path.join(tessdata_dir, 'chi_sim.traineddata')
    if not os.path.exists(chi_sim_path):
        print("\n⚠️ 警告：未找到中文语言包，将只用英文识别")
    return True
 
def select_pdf_file():
    root = tk.Tk()
    root.withdraw()
    print("==================================================")
    print(" 📂 选择扫描版 PDF 文件")
    print("==================================================")
    file_path = filedialog.askopenfilename(
        title="选择要转换的 PDF",
        filetypes=[("PDF 文件", "*.pdf"), ("所有文件", "*.*")]
    )
    if not file_path: return None
    print(f"✅ 已选择: {file_path}")
    return file_path
 
def get_pdf_page_count(input_path):
    try:
        from pypdf import PdfReader
        return len(PdfReader(input_path).pages)
    except: return None
 
def process_single_page(args):
    """单页处理任务（在独立线程中运行）"""
    input_path, page_num, dpi = args
    from pdf2image import convert_from_path
    import pytesseract
    
    temp_path = None
    try:
        # 1. 转换图片
        images = convert_from_path(
            input_path, dpi=dpi, first_page=page_num, last_page=page_num, fmt='png', thread_count=1
        )
        if not images: return page_num, None
        
        image = images[0]
        
        # 2. OCR
        try:
            pdf_bytes = pytesseract.image_to_pdf_or_hocr(image, extension='pdf', lang='chi_sim+eng')
        except:
            pdf_bytes = pytesseract.image_to_pdf_or_hocr(image, extension='pdf', lang='eng')
 
        # 3. 保存为临时文件
        # 注意：这里不使用 delete=False，手动管理生命周期更安全
        fd, temp_path = tempfile.mkstemp(suffix='.pdf')
        with os.fdopen(fd, 'wb') as tmp:
            tmp.write(pdf_bytes)
            
        return page_num, temp_path
 
    except Exception as e:
        return page_num, None
    finally:
        # === 关键内存释放 ===
        if 'images' in locals() and images:
            for img in images: img.close()
        if 'image' in locals(): del image
        if 'pdf_bytes' in locals(): del pdf_bytes
        # 子线程结束前强制 GC
        gc.collect()
 
def merge_chunk_pages(temp_files, output_writer):
    """
    将一批临时文件合并入 Writer，并删除临时文件
    """
    from pypdf import PdfReader
    for temp_path in temp_files:
        if temp_path and os.path.exists(temp_path):
            try:
                with open(temp_path, 'rb') as f:
                    reader = PdfReader(f)
                    if reader.pages:
                        output_writer.add_page(reader.pages[0])
            except Exception as e:
                print(f"合并页面失败: {e}")
            finally:
                # 立即删除临时文件，释放磁盘和内存句柄
                os.remove(temp_path)
 
def convert_pdf_safe(input_path: str, dpi: int = 150):
    print("\n" + "=" * 50)
    print(f" 🛡️ 大文件稳定模式 (每{CHUNK_SIZE}页保存一次)")
    print("=" * 50)
 
    try:
        import pytesseract
        from pypdf import PdfWriter
        pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        return None
 
    input_dir = os.path.dirname(input_path)
    input_name = os.path.splitext(os.path.basename(input_path))[0]
    output_path = os.path.join(input_dir, f"{input_name}_文字版.pdf")
 
    counter = 1
    while os.path.exists(output_path):
        output_path = os.path.join(input_dir, f"{input_name}_文字版_{counter}.pdf")
        counter += 1
 
    start_time = time.time()
    
    try:
        page_count = get_pdf_page_count(input_path)
        print(f"📖 共 {page_count} 页，开始处理...")
        
        writer = PdfWriter()
        # 用于收集当前块的临时文件路径
        current_chunk_temps = {} 
        completed_count = 0
        print_lock = threading.Lock()
 
        # 准备所有任务
        tasks = [(input_path, i, dpi) for i in range(1, page_count + 1)]
        
        print(f"🚀 启动 {MAX_WORKERS} 个线程...")
 
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_page = {executor.submit(process_single_page, task): task[1] for task in tasks}
            
            for future in as_completed(future_to_page):
                page_num, temp_path = future.result()
                
                # 收集结果
                if temp_path:
                    current_chunk_temps[page_num] = temp_path
                
                completed_count += 1
                
                # === 核心：分块写入逻辑 ===
                # 每处理完 CHUNK_SIZE 页，或者到了最后一页，就执行一次合并写入
                if completed_count % CHUNK_SIZE == 0 or completed_count == page_count:
                    # 按页码排序，确保顺序正确
                    sorted_keys = sorted(current_chunk_temps.keys())
                    files_to_merge = [current_chunk_temps[k] for k in sorted_keys]
                    
                    # 合并并写入 Writer
                    merge_chunk_pages(files_to_merge, writer)
                    
                    # 清空当前缓存，释放内存
                    current_chunk_temps.clear()
                    
                    # 打印进度
                    with print_lock:
                        elapsed = time.time() - start_time
                        avg_time = elapsed / completed_count
                        remaining = avg_time * (page_count - completed_count)
                        print(f"\r  ✅ 已处理 {completed_count}/{page_count} | "
                              f"💾 已保存 | 剩余: {remaining/60:.1f}分钟", end='')
 
        print("\n\n💾 正在写入最终文件...")
        
        # 最终保存
        with open(output_path, 'wb') as f:
            writer.write(f)
 
        total_time = time.time() - start_time
        print(f"\n✅ 完成！总耗时: {total_time/60:.1f} 分钟")
        return output_path
 
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n❌ 失败: {e}")
        return None
 
def main():
    if not check_dependencies(): return
    input_pdf = select_pdf_file()
    if not input_pdf: return
    
    print("\n⚙️  选择清晰度 (内存安全优先):")
    print("  [1] 100 DPI (推荐大文件，极省内存)")
    print("  [2] 150 DPI (平衡)")
    
    choice = input("👉 选择 (默认 2): ").strip()
    dpi = 100 if choice == '1' else 150
    
    convert_pdf_safe(input_pdf, dpi=dpi)
 
if __name__ == "__main__":
    main()