import os
import tkinter as tk
from tkinter import filedialog
from pypdf import PdfReader, PdfWriter


def select_pdf_file_gui():
    """使用 GUI 文件对话框选择 PDF 文件"""
    # 创建隐藏的主窗口
    root = tk.Tk()
    root.withdraw()

    print("==================================================")
    print(" 📂 PDF 文件选择器")
    print("==================================================")

    # 打开文件选择对话框
    file_path = filedialog.askopenfilename(
        title="选择要拆分的 PDF 文件",
        filetypes=[("PDF 文件", "*.pdf"), ("所有文件", "*.*")]
    )

    if not file_path:
        print("❌ 未选择文件，程序退出。")
        return None

    print(f"✅ 已选择文件: {file_path}")
    return file_path


def split_pdf_by_pages(input_path: str, pages_per_chunk: int = 150):
    print("==================================================")
    print(" 🔪 物理快刀：重型扫描版 PDF 自动拆分器")
    print("==================================================")

    # 去除路径中可能带有的双引号
    input_path = input_path.strip('"\'')

    if not os.path.exists(input_path):
        print(f"❌ 找不到文件，请检查路径是否正确: {input_path}")
        return

    print(f"📄 正在读取目标大作: {os.path.basename(input_path)}")

    try:
        reader = PdfReader(input_path)
        total_pages = len(reader.pages)
        print(f"📖 扫描完毕，全书共计: {total_pages} 页")

        # 获取原文件名（不带 .pdf 后缀）
        base_name = os.path.splitext(os.path.basename(input_path))[0]

        # 用原书名字，在同级目录下创建一个同名文件夹
        output_dir = os.path.join(os.path.dirname(input_path), base_name)
        os.makedirs(output_dir, exist_ok=True)
        print(f"📂 已为您创建专属收纳文件夹: {output_dir}")
        print("-" * 50)

        # 开始按页数切片
        for i in range(0, total_pages, pages_per_chunk):
            writer = PdfWriter()
            start_page = i
            end_page = min(i + pages_per_chunk, total_pages)

            for page_num in range(start_page, end_page):
                writer.add_page(reader.pages[page_num])

            part_num = (i // pages_per_chunk) + 1
            output_filename = os.path.join(output_dir, f"{base_name}_Part{part_num}.pdf")

            with open(output_filename, "wb") as out_file:
                writer.write(out_file)

            print(f"  ✅ 成功切出: Part {part_num} (包含原书第 {start_page + 1} 到 {end_page} 页)")

        print("-" * 50)
        print(f"🎉 拆分完美收工！")
        print(f"👉 所有切片已整齐存放在: {output_dir}")

    except Exception as e:
        print(f"❌ 拆分发生致命错误: {e}")


def get_pages_per_chunk():
    """获取每块页数"""
    print("\n" + "=" * 50)
    print(" ⚙️  分块设置")
    print("=" * 50)
    print("  建议值:")
    print("    - 150 页: 普通扫描版 (默认)")
    print("    - 100 页: 高清彩图扫描版")
    print("    - 200 页: 文字为主的小说/书籍")

    choice = input("👉 请输入每块页数 (直接回车使用默认 150): ").strip()

    if not choice:
        return 150

    if choice.isdigit():
        pages = int(choice)
        if pages > 0:
            return pages
        else:
            print("❌ 页数必须大于 0，使用默认值 150")
            return 150
    else:
        print("❌ 无效输入，使用默认值 150")
        return 150


if __name__ == "__main__":
    # 使用 GUI 对话框选择文件
    target_pdf = select_pdf_file_gui()

    if target_pdf is None:
        exit(1)

    # 获取每块页数
    pages_per_chunk = get_pages_per_chunk()

    # 开始拆分
    split_pdf_by_pages(target_pdf, pages_per_chunk)
