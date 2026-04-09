import os
import time
import logging
import hashlib
import gc
import re
import csv
import json  
import fitz  # PyMuPDF
from typing import List

# 引入全局中枢与核心组件
from ingest_engine.config.settings import settings
from ingest_engine.domain.schemas import VisualLedger
from ingest_engine.components.file_parser import FileCrawler
from ingest_engine.components.vision_core import DualTrackEngine
from ingest_engine.components.chroma_adapter import ChromaRepository

# 配置日志输出格式
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ingest_engine.pipeline")

class IngestionPipeline:
    def __init__(self, target_path: str = None):
        self.target_path = target_path 
        # 重新挂载视觉引擎，用于处理少量图片的 PDF
        self.vision_engine = DualTrackEngine() 
        self.vector_db = ChromaRepository()
    
    def _compute_file_hash(self, file_path: str) -> str:
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for byte_block in iter(lambda: f.read(65536), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except Exception:
            return "unknown_hash"

    def _determine_category(self, file_path: str) -> str:
        path_lower = file_path.lower().replace("\\", "/")
        for category, keywords in settings.category_keywords.items():
            if any(kw in path_lower for kw in keywords):
                return category
        return "shared_common"

    def _auto_detect_language(self, file_name: str) -> str:
        if re.search(r'[\u4e00-\u9fa5]', file_name):
            return "zh"
        return "en"

    def _is_large_pdf(self, file_path: str, max_pages: int) -> bool:
        if not file_path.lower().endswith('.pdf'):
            return False
        try:
            with fitz.open(file_path) as doc:
                if len(doc) > max_pages:
                    return True
        except Exception:
            return False 
        return False

    def _is_scanned_pdf(self, file_path: str) -> bool:
        """🚨 核心防御：智能侦测纯图片扫描件"""
        if not file_path.lower().endswith('.pdf'):
            return False
        try:
            with fitz.open(file_path) as doc:
                if len(doc) == 0: return False
                check_pages = min(len(doc), 5)
                total_text_chars = sum(len(doc[i].get_text("text").strip()) for i in range(check_pages))
                if check_pages > 0 and (total_text_chars / check_pages) < 20:
                    return True
        except Exception:
            pass
        return False

    def _get_image_count(self, file_path: str) -> int:
        """📸 视觉雷达：极速计算 PDF 包含的图片总数"""
        try:
            with fitz.open(file_path) as doc:
                return sum(len(page.get_images(full=True)) for page in doc)
        except Exception:
            return 0

    def _chunk_text(self, text: str, chunk_size: int = 800, overlap: int = 1):
        """智能无损切块器"""
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        chunks, current_paras, current_len = [], [], 0
        for p in paragraphs:
            current_paras.append(p)
            current_len += len(p)
            if current_len >= chunk_size:
                chunks.append("\n\n".join(current_paras))
                current_paras = current_paras[-overlap:] if overlap > 0 else []
                current_len = sum(len(cp) for cp in current_paras)
        if current_paras:
            if len(chunks) > 0 and current_len < (chunk_size // 2):
                chunks[-1] += "\n\n" + "\n\n".join(current_paras)
            else:
                chunks.append("\n\n".join(current_paras))
        return chunks

    def run(self):
        logger.info("🚀 启动 SSP 智能路由流水线 (自动分发小图PDF与重型PDF)...")
        
        if self.target_path and os.path.isfile(self.target_path):
            files = [self.target_path]
        else:
            scan_dir = self.target_path if self.target_path else settings.kb_base_path
            crawler = FileCrawler(root_dir=scan_dir, blacklist=settings.blacklist_files)
            files = crawler.scan()
            
        IMAGE_THRESHOLD = 30 # 👑 设置轻量视觉的极限阈值 (可自行修改)
        
        skipped_count = large_file_count = scanned_file_count = redirected_count = processed_count = 0
        
        for idx, file_path in enumerate(files):
            file_name = os.path.basename(file_path)
            ext = file_name.lower().split('.')[-1]
            
            try:
                file_hash = self._compute_file_hash(file_path)
                if self.vector_db.is_file_indexed(file_hash):
                    logger.info(f"⏭️  [{idx+1}/{len(files)}] 跳过已入库: {file_name}")
                    skipped_count += 1
                    continue

                category = self._determine_category(file_path)
                doc_lang = self._auto_detect_language(file_name)
                
                force_fast_text = False
                use_light_vlm = False
                
                # =========================================================
                # 🛡️ PDF 智能路由中枢
                # =========================================================
                if ext == 'pdf':
                    if self._is_scanned_pdf(file_path):
                        logger.warning(f"🚫 [拦截] 纯图片扫描件，请先使用 ocr_pdf_to_pdf.py 洗底: {file_name}")
                        scanned_file_count += 1
                        continue
                        
                    is_screenplay = (category == "screenplay_expert")
                    max_pages = settings.standard_limits.get("max_pages", 200)
                    if not is_screenplay and self._is_large_pdf(file_path, max_pages):
                        logger.warning(f"🛑 触发熔断! 超大文件: {file_name}")
                        large_file_count += 1
                        continue

                    # 📸 启动图像雷达侦测
                    img_count = self._get_image_count(file_path)
                    is_text_version = "_文字版" in file_name or "-文字版" in file_name
                    
                    if is_text_version or img_count == 0:
                        force_fast_text = True
                        logger.info(f"⚡ [PDF 直通车] 侦测到 0 图或文字版标记，极速抽取文本: {file_name}")
                    elif img_count <= IMAGE_THRESHOLD:
                        use_light_vlm = True
                        logger.info(f"📸 [轻量视觉] 包含 {img_count} 张图 (≤{IMAGE_THRESHOLD})，Mode 4 内部唤醒 VLM: {file_name}")
                    else:
                        logger.warning(f"🛑 [重装路由拦截] 这本书太重了！包含多达 {img_count} 张图片！: {file_name}")
                        logger.warning(f"💡 提示: 已将其拦截，请移交至【Stage 1-3 多模态大一统车间】单独处理。")
                        redirected_count += 1
                        continue

                # =========================================================
                # 🚀 通道 A: 极速全格式引擎 (CSV/JSON/MD/TXT/免图PDF)
                # =========================================================
                if ext in ['csv', 'json', 'md', 'txt'] or force_fast_text:
                    valid_chunks, valid_metas = [], []
                    try:
                        if ext == 'csv':
                            with open(file_path, 'r', encoding='utf-8-sig') as f:
                                reader = csv.DictReader(f)
                                headers = reader.fieldnames
                                if headers:
                                    for i, row in enumerate(reader):
                                        row_elements = [f"{col}: {str(row.get(col)).strip()}" for col in headers if row.get(col)]
                                        if semantic_text := " | ".join(row_elements):
                                            valid_chunks.append((i, semantic_text))

                        elif ext == 'json':
                            with open(file_path, 'r', encoding='utf-8') as f:
                                data = json.load(f)
                                if isinstance(data, list):
                                    for i, item in enumerate(data):
                                        valid_chunks.append((i, json.dumps(item, ensure_ascii=False)))
                                else:
                                    valid_chunks.append((0, json.dumps(data, ensure_ascii=False)))

                        elif ext in ['md', 'txt']:
                            with open(file_path, 'r', encoding='utf-8') as f:
                                raw_chunks = self._chunk_text(f.read())
                            for i, chunk in enumerate(raw_chunks):
                                valid_chunks.append((i, chunk))
                                
                        elif ext == 'pdf' and force_fast_text:
                            with fitz.open(file_path) as doc:
                                content = "".join(page.get_text("text").strip() + "\n\n" for page in doc if page.get_text("text").strip())
                            raw_chunks = self._chunk_text(content)
                            for i, chunk in enumerate(raw_chunks):
                                valid_chunks.append((i, chunk))

                        if valid_chunks:
                            insert_chunks, insert_metas = [], []
                            for chunk_idx, chunk_text in valid_chunks:
                                chunk_meta = {
                                    "source": file_name, "file_path": file_path, "file_hash": file_hash, 
                                    "kb_category": category, "language": doc_lang, "chunk_index": chunk_idx,
                                    "engine_ver": f"{ext.upper()}-FastTrack-V6"
                                }
                                chunk_meta["chunk_hash"] = hashlib.sha256(f"{file_name}_{file_hash}_chunk{chunk_idx}_{chunk_text[:30]}".encode()).hexdigest()
                                insert_chunks.append(chunk_text)
                                insert_metas.append(chunk_meta)

                            count = self.vector_db.add_batches(insert_chunks, insert_metas)
                            if count > 0:
                                logger.info(f"✅ 入库成功: {file_name} -> {category}_{doc_lang}")
                                processed_count += 1
                    except Exception as e:
                        logger.error(f"❌ 读取文件失败: {file_name} | {e}")
                    gc.collect()
                    continue

                # =========================================================
                # 🎬 通道 B: 轻量视觉引擎 (少图 PDF 专属)
                # =========================================================
                if ext == 'pdf' and use_light_vlm:
                    ledger = VisualLedger(file_path=file_path, file_hash=file_hash, skip_images=False)
                    ledger = self.vision_engine.process(ledger)

                    if ledger.vision_result and ledger.vision_result.ocr_text:
                        meta = {
                            "source": file_name, "file_path": file_path, "file_hash": file_hash,
                            "kb_category": category, "language": doc_lang, 
                            "processed_time": time.strftime("%Y-%m-%d %H:%M:%S")
                        }
                        count = self.vector_db.add_document(ledger.vision_result.ocr_text, meta)
                        if count > 0:
                            logger.info(f"✅ 入库成功 (含视觉解析): {file_name} -> {category}_{doc_lang}")
                            processed_count += 1
                    
                    del ledger
                    gc.collect()
                
            except Exception as e:
                logger.error(f"❌ 处理文件异常: {file_name} | {e}", exc_info=True)
                continue
                
        logger.info(f"🏁 流水线完毕！成功: {processed_count} | 重型路由拦截: {redirected_count} | 扫描件拦截: {scanned_file_count}")

if __name__ == "__main__":
    IngestionPipeline().run()