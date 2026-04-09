import os
import re
import time
import hashlib
import logging
import glob
from ingest_engine.config.settings import settings
from ingest_engine.components.chroma_adapter import ChromaRepository

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("Stage3_Markdown_Embed_V4")

def clean_source_name(folder_name: str) -> str:
    clean_name = re.split(r'_Part|-Part|_文字版|_VLM|_Project', folder_name)[0]
    return clean_name

def generate_chunk_hash(text_chunk: str, source_name: str, chunk_index: int) -> str:
    unique_string = f"{source_name}_chunk{chunk_index}_{text_chunk}"
    return hashlib.sha256(unique_string.encode('utf-8')).hexdigest()

def chunk_markdown_by_paragraphs(text: str, chunk_size: int = 800, overlap_paras: int = 1):
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    chunks = []
    
    current_paras = []
    current_len = 0
    
    for p in paragraphs:
        current_paras.append(p)
        current_len += len(p)
        
        if current_len >= chunk_size:
            chunks.append("\n\n".join(current_paras))
            
            # 🛡️ 核心修复：智能防重叠 (Anti-Overlap Check)
            potential_overlaps = current_paras[-overlap_paras:] if overlap_paras > 0 else []
            safe_overlaps = []
            
            for overlap_p in potential_overlaps:
                # 🚨 终极绝对防御：只要包含以下任何一个视觉特征，绝对禁止重叠！
                # 兼容 stage2 的 "AI 导演视觉解析" 和 vision_core 的 "AI视觉锚点"
                if not any(kw in overlap_p for kw in ["🖼️", "[PENDING_IMG", "[AI_VISION_TARGET"]):
                    safe_overlaps.append(overlap_p)
            
            current_paras = safe_overlaps
            current_len = sum(len(cp) for cp in current_paras)
            
    if current_paras:
        if len(chunks) > 0 and current_len < (chunk_size // 2):
            chunks[-1] += "\n\n" + "\n\n".join(current_paras)
        else:
            chunks.append("\n\n".join(current_paras))
            
    return chunks

def process_project_bundle(project_dir: str, repo: ChromaRepository, global_stats: dict):
    vlm_md_dir = os.path.join(project_dir, "03_VLM_MD")
    if not os.path.exists(vlm_md_dir):
        vlm_md_dir = project_dir
        
    md_files = sorted(glob.glob(os.path.join(vlm_md_dir, "*_VLM.md")))
    if not md_files:
        logger.warning(f"⚠️ 在 {os.path.basename(project_dir)} 中没有找到任何 _VLM.md 文件！跳过。")
        return
        
    project_name = os.path.basename(project_dir.rstrip("\\/"))
    source_name = clean_source_name(project_name)
    
    print(f"\n📖 启动【大一统】缝合协议: 目标母体 【{source_name}】")
    print(f"📥 正在内存中融合 {len(md_files)} 个物理分卷...")
    
    full_text = ""
    for f in md_files:
        with open(f, 'r', encoding='utf-8') as file:
            full_text += file.read() + "\n\n"
            
    chunks = chunk_markdown_by_paragraphs(full_text, chunk_size=800, overlap_paras=1)
    print(f"📦 完美切片: 全书已被无损划分为 {len(chunks)} 个语义块。")
    
    kb_category = "director_expert"
    doc_lang = "en" if not re.search(r'[\u4e00-\u9fa5]', source_name) else "zh"
    
    valid_chunks = []
    valid_metas = []
    skipped_count = 0
    
    print("🔍 正在执行基因指纹查重...")
    for i, chunk in enumerate(chunks):
        chunk_hash = generate_chunk_hash(chunk, source_name, i)
        
        if repo.is_file_indexed(chunk_hash):
            skipped_count += 1
            global_stats["skipped"] += 1
            continue
            
        meta = {
            "source": source_name,
            "file_path": f"{source_name}_Full_Volume",
            "file_hash": chunk_hash,
            "chunk_index": i,  
            "kb_category": kb_category,
            "language": doc_lang,
            "processed_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "engine_ver": "Stage3-MD-Pro-V4"
        }
        valid_chunks.append(chunk)
        valid_metas.append(meta)
        
    if valid_chunks:
        # 👑 直接把查重通过的所有块，一次性喂给底层的流式批处理引擎！
        success_count = repo.add_batches(valid_chunks, valid_metas)
        global_stats["success"] += success_count
    else:
        success_count = 0

    print(f"   └─ 战报: {success_count} 块新增入库, {skipped_count} 块因重复被拦截。")

def run(target_path: str = None):
    print("==================================================")
    print("🚀 终极 Stage 3 (V4 批量版): 大一统切块 + CPU流式批处理对接")
    print("==================================================")
    
    if not target_path:
        target_path = input("📂 请输入【单个 _Project 文件夹】或【包含多个工程的父文件夹】:\n> ").strip('"\'')
        
    repo = ChromaRepository()
    global_stats = {"success": 0, "skipped": 0}
    
    if os.path.isdir(target_path):
        # 智能侦测：如果是单个工程包 (包含 03_VLM_MD 目录 或 以 _Project 结尾)
        if os.path.exists(os.path.join(target_path, "03_VLM_MD")) or target_path.endswith("_Project"):
            process_project_bundle(target_path, repo, global_stats)
        else:
            # 批量扫描：寻找父文件夹下的所有子工程包
            project_dirs = []
            for d in os.listdir(target_path):
                full_path = os.path.join(target_path, d)
                # 判断条件：是个文件夹，且以 _Project 结尾 或 里面直接有 03_VLM_MD 目录
                if os.path.isdir(full_path) and (d.endswith("_Project") or os.path.exists(os.path.join(full_path, "03_VLM_MD"))):
                    project_dirs.append(full_path)
            
            if not project_dirs:
                logger.error(f"❌ 在 {target_path} 下没有找到任何有效的 _Project 工程包！")
            else:
                print(f"📦 侦测到批量任务！共发现 {len(project_dirs)} 个工程包待处理。")
                for i, p_dir in enumerate(project_dirs):
                    print(f"\n" + "-"*50)
                    print(f"▶️ 开始处理 第 {i+1}/{len(project_dirs)} 个工程: {os.path.basename(p_dir)}")
                    process_project_bundle(p_dir, repo, global_stats)
    else:
        logger.error("❌ 路径无效，请提供文件夹路径。")
        
    print("\n" + "👑"*25)
    print(f"✅ 全线工程包大一统批量入库完毕！")
    print(f"   📈 数据库总计新增: {global_stats['success']} 个无损知识锚点")
    print(f"   🛡️ 成功拦截重复块: {global_stats['skipped']} 个")
    print("👑"*25 + "\n")

if __name__ == "__main__":
    run()