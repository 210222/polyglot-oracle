import os
import re
import fitz  # PyMuPDF
import logging
from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("Stage1_Markdown")

def create_project_bundle(pdf_path, base_output_dir="data/processed"):
    """
    👑 核心升级：智能工程包收纳系统
    自动识别书名并建立专属的 Project 文件夹。
    例如：读取 "光影大师_Part1_文字版.pdf" -> 会自动建立 "光影大师_Project" 文件夹
    """
    filename = os.path.basename(pdf_path)
    name_without_ext = os.path.splitext(filename)[0]
    
    # 智能剥离后缀，提取真正的书名（兼容 _Part1, _文字版, -Part 等格式）
    project_name = re.split(r'_Part|-Part|_文字版', name_without_ext)[0]
    
    bundle_dir = os.path.join(base_output_dir, f"{project_name}_Project")
    img_dir = os.path.join(bundle_dir, "01_Images_Assets")
    md_dir = os.path.join(bundle_dir, "02_Raw_MD")
    
    # 建立物理隔离的专属车间
    os.makedirs(img_dir, exist_ok=True)
    os.makedirs(md_dir, exist_ok=True)
    
    return bundle_dir, img_dir, md_dir, name_without_ext

def process_pdf_to_md(pdf_path):
    """
    分离图文，并生成带“装甲防弹标记”的 Markdown 实体文件
    """
    bundle_dir, img_dir, md_dir, doc_name = create_project_bundle(pdf_path)
    logger.info(f"\n📂 锁定专属工程包: {bundle_dir}")
    
    try:
        # 得益于你之前做的“双层 PDF”处理，这里打开和读取会极其丝滑
        doc = fitz.open(pdf_path)
    except Exception as e:
        logger.error(f"❌ 无法打开 PDF: {e}")
        return
    
    md_content = []
    md_content.append(f"# 📖 原始卷宗: {doc_name}\n\n")
    
    img_count = 0
    for page_num in tqdm(range(len(doc)), desc=f"解析 {doc_name}"):
        page = doc[page_num]
        
        # 1. 极速抽取文字 (直接抽取你贴上的透明文字层，抛弃极慢的 CPU OCR)
        text = page.get_text("text")
        if text.strip():
            md_content.append(text.strip() + "\n\n")
        
        # 2. 物理切割图片
        image_list = page.get_images(full=True)
        for img_index, img in enumerate(image_list):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image["ext"]
            
            # 过滤掉小于 15KB 的噪点图或装饰线
            if len(image_bytes) < 15360:
                continue
            
            # 保存高清图片到 01_Images_Assets 文件夹
            img_name = f"{doc_name}_P{page_num+1}_{img_index+1}.{image_ext}"
            img_path = os.path.abspath(os.path.join(img_dir, img_name))
            
            with open(img_path, "wb") as f:
                f.write(image_bytes)
            
            img_count += 1
            
            # 🛡️ 核心绝杀：植入“装甲防弹标记”！
            # 把它极其醒目地嵌在文字中间，并在里面写死图片的绝对物理路径。
            # 这样无论你怎么改文字，Stage 2 都能像猎犬一样精准闻着绝对路径找到图！
            md_content.append(f"\n\n👉👉👉 [AI_VISION_TARGET: {img_path}] 👈👈👈\n\n")
            
    # 3. 将内容固化为 Markdown 实体文件
    md_file_path = os.path.join(md_dir, f"{doc_name}.md")
    with open(md_file_path, "w", encoding="utf-8") as f:
        f.write("".join(md_content))
        
    print("\n" + "="*50)
    print(f"✅ 【{doc_name}】 实体化切割完成！")
    print(f"   📝 纯文本骨架已生成: {md_file_path}")
    print(f"   🖼️ 高清原图已提取: {img_count} 张 (存入 01_Images_Assets)")
    print(f"   💡 你现在可以直接用记事本打开上面的 .md 文件进行人类质检了！")
    print("="*50 + "\n")

def run(target_path: str = None):
    print("==================================================")
    print("🚀 全新 Stage 1: Markdown 实体化图文分离引擎 (工程包版)")
    print("==================================================")
    
    if not target_path:
        target_path = input("📂 请输入 PDF 文件或文件夹路径: ").strip('"\'')
        
    if os.path.isfile(target_path) and target_path.lower().endswith(".pdf"):
        process_pdf_to_md(target_path)
    elif os.path.isdir(target_path):
        pdf_files = [f for f in os.listdir(target_path) if f.lower().endswith('.pdf')]
        if not pdf_files:
            logger.warning("⚠️ 该文件夹下没有找到 PDF 文件！")
            return
            
        print(f"📦 发现文件夹，共有 {len(pdf_files)} 个 PDF 切片待处理，开始单件流水线...")
        for f in pdf_files:
            process_pdf_to_md(os.path.join(target_path, f))
    else:
        logger.error("❌ 路径无效或不是 PDF 文件。")

if __name__ == "__main__":
    run()