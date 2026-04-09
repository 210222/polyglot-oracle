import re
import os
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

def extract_text_from_epub(epub_path):
    """从 EPUB 文件中提取纯净的文本"""
    book = epub.read_epub(epub_path)
    all_text = []
    
    # 遍历 EPUB 中的所有 HTML 章节
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            # 使用 BeautifulSoup 解析 HTML 并提取纯文本
            soup = BeautifulSoup(item.get_body_content(), 'html.parser')
            text = soup.get_text(separator='\n')
            all_text.append(text)
            
    return '\n'.join(all_text)

def parse_master_shots_epub(file_path):
    """直接读取 EPUB 并进行智能切片"""
    if not os.path.exists(file_path):
        print(f"⚠️ 文件未找到: {file_path}")
        return []

    print(f"📖 正在解析 EPUB 文件: {os.path.basename(file_path)}...")
    
    # 1. 先把 EPUB 转化为纯净的长文本
    text = extract_text_from_epub(file_path)

    # 2. 识别大章节 (例如：第一章 打斗镜头)
    chapter_pattern = re.compile(r'(第[一二三四五六七八九十]+章\s+[^\n]+)')
    
    # 3. 识别小技巧 (例如：1.1 长焦特效)
    section_pattern = re.compile(r'(\n\d+\.\d+\s+[^\n]+)')

    book_title = os.path.basename(file_path).split('.')[0]
    all_chunks = []
    current_chapter = "未分类"

    # 按大章节分割
    chapter_splits = chapter_pattern.split(text)
    
    for i in range(len(chapter_splits)):
        part = chapter_splits[i]
        if chapter_pattern.match(part):
            current_chapter = part.strip()
        else:
            # 按小技巧(1.1, 1.2...)切片
            section_splits = section_pattern.split(part)
            current_section = "前言/概述"

            for j in range(len(section_splits)):
                sub_part = section_splits[j]
                if section_pattern.match(sub_part):
                    current_section = sub_part.strip()
                elif len(sub_part.strip()) > 50:
                    # 🎯 生成带有元数据的知识块
                    chunk_text = f"【{current_chapter} - {current_section}】\n{sub_part.strip()}"
                    
                    metadata = {
                        "source": book_title,
                        "chapter": current_chapter,
                        "technique_name": current_section,
                        "content_type": "camera_technique"
                    }
                    
                    all_chunks.append({
                        "text": chunk_text,
                        "metadata": metadata
                    })

    print(f"✅ 《{book_title}》智能切片完成！共生成 {len(all_chunks)} 个高质量技巧知识块。")
    return all_chunks

if __name__ == "__main__":
    import tkinter as tk
    from tkinter import filedialog

    # 隐藏主窗口，直接弹出文件选择框
    root = tk.Tk()
    root.withdraw()

    print("🖱️ 请选择您下载的《大师镜头》或《镜头设计》EPUB 文件...")
    epub_path = filedialog.askopenfilename(
        title="选择 EPUB 电子书",
        filetypes=[("EPUB 文件", "*.epub")]
    )

    if epub_path:
        chunks = parse_master_shots_epub(epub_path)

        # 打印前 3 个切片看看效果
        print("\n" + "="*50 + " 切片效果预览 " + "="*50)
        for i, chunk in enumerate(chunks[:3]):
            print(f"\n📦 Chunk {i+1}:")
            print(f"🏷️ 标签: {chunk['metadata']}")
            print(f"📄 内容前 100 字: {chunk['text'][:100].replace(chr(10), ' ')}...")