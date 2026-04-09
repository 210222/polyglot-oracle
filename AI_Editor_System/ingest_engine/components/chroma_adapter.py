import os
import logging
import gc
import hashlib
import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.utils import embedding_functions
import opencc 

from ingest_engine.config.settings import settings

logger = logging.getLogger("ingest_engine.chroma_adapter")

class LocalEmbedModelAdapter:
    """
    [本地模型桥接层] 专门为了兼容 logic.py 中调用的 repo.embed_model.encode
    拦截并转换本地模型的输出格式。
    """
    def __init__(self, embedding_function):
        self.ef = embedding_function

    def encode(self, texts: list, normalize_embeddings: bool = True):
        embeddings = self.ef(texts)
        class ResultMock:
            def __init__(self, vec): self.vec = vec
            def tolist(self): return self.vec
        return [ResultMock(vec) for vec in embeddings]


class ChromaRepository:
    """
    ChromaDB 仓储模式实现：路线 1 (双核本地极速版)
    完全物理隔离中文和英文向量，杜绝跨语言污染。
    """
    def __init__(self):
        self.persist_dir = settings.db.chroma_persist_dir
        os.makedirs(self.persist_dir, exist_ok=True)
        
        self.client = chromadb.PersistentClient(
            path=self.persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False)
        )
        
        # 挂载本地中文核心引擎
        logger.info("🧠 正在挂载本地中文核心: BAAI/bge-small-zh-v1.5")
        self.zh_embed = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="BAAI/bge-small-zh-v1.5"
        )
        
        # 挂载本地英文核心引擎
        logger.info("🧠 正在挂载本地英文核心: BAAI/bge-small-en-v1.5")
        self.en_embed = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="BAAI/bge-small-en-v1.5"
        )
        
        # 初始化繁简转换器
        self.cc = opencc.OpenCC('t2s')
        
        # 适配层
        self.embed_model = LocalEmbedModelAdapter(self.zh_embed)
        
        # 动态创建独立的中英双轨数据表
        self.collections = {}
        for category in settings.category_keywords.keys():
            self.collections[f"{category}_zh"] = self.client.get_or_create_collection(
                name=f"{category}_zh", embedding_function=self.zh_embed
            )
            self.collections[f"{category}_en"] = self.client.get_or_create_collection(
                name=f"{category}_en", embedding_function=self.en_embed
            )

    def is_file_indexed(self, file_hash: str) -> bool:
        """全库级查重防御：基于整书物理指纹检索"""
        for cat_name, collection in self.collections.items():
            try:
                results = collection.get(
                    where={"file_hash": file_hash}, limit=1, include=["metadatas"]
                )
                if results and results.get("ids") and len(results["ids"]) > 0:
                    return True
            except Exception:
                pass
        return False

    def add_batches(self, chunks: list, metas: list) -> int:
        """
        👑 终极融合版：完美段落切块 + CPU 流式批处理引擎 + 智能 ID 分发
        """
        if not chunks:
            return 0

        # 🎯 动态决定挂载点
        doc_lang = metas[0].get("language", "zh").lower()
        base_category = metas[0].get("kb_category", "shared_common")
        
        target_collection_name = f"{base_category}_{doc_lang}"
        if target_collection_name not in self.collections:
            target_collection_name = f"shared_common_{doc_lang}"
            
        target_collection = self.collections[target_collection_name]

        batch_size = 32  
        chunks_batch = []
        metadatas_batch = []
        ids_batch = []
        total_inserted = 0
        total_chunks = len(chunks)
        
        print(f"\n    [CPU 流式引擎启动] 正在高速向量化完美切片，批次大小: {batch_size}块/次")

        for chunk, meta in zip(chunks, metas):
            # 物理消灭繁简鸿沟
            if doc_lang == "zh":
                chunk = self.cc.convert(chunk)

            chunks_batch.append(chunk)
            metadatas_batch.append(meta)
            
            # 👑 核心修复：提取防碰撞绝对 ID 
            chunk_id = meta.get('chunk_hash')
            if not chunk_id:
                base_hash = meta.get('file_hash', 'default_hash')
                c_idx = meta.get('chunk_index', total_inserted)
                chunk_id = f"{base_hash}_chunk_{c_idx}"
                
            ids_batch.append(chunk_id)
            
            total_inserted += 1
            
            # 当盘子满了 32 块，立刻交给数据库秒杀
            if len(chunks_batch) >= batch_size:
                try:
                    target_collection.add(
                        documents=chunks_batch,
                        metadatas=metadatas_batch,
                        ids=ids_batch
                    )
                    print(f"\r    🚀 [吞噬进度] CPU 已将 {total_inserted}/{total_chunks} 个块转化为高维坐标存入...", end="", flush=True)
                except Exception as e:
                    logger.error(f"\n批次插入失败: {e}")
                
                chunks_batch.clear()
                metadatas_batch.clear()
                ids_batch.clear()

        # 收尾剩余的几块尾巴
        if chunks_batch:
            try:
                target_collection.add(
                    documents=chunks_batch,
                    metadatas=metadatas_batch,
                    ids=ids_batch
                )
                print(f"\r    🚀 [吞噬进度] CPU 已将 {total_inserted}/{total_chunks} 个块转化为高维坐标存入... (完成)", end="", flush=True)
            except Exception as e:
                pass
                
        print() 
        gc.collect() 
        return total_inserted

    def add_document(self, text_content: str, meta: dict) -> int:
        """
        🔌 [向下兼容转接头] 专为旧版直通车脚本保留的入口。
        """
        if not text_content or len(text_content.strip()) < 10:
            return 0

        # 1. 智能切块 
        paragraphs = [p.strip() for p in text_content.split('\n\n') if p.strip()]
        chunks = []
        current_paras = []
        current_len = 0
        chunk_size = 800
        
        for p in paragraphs:
            current_paras.append(p)
            current_len += len(p)
            if current_len >= chunk_size:
                chunks.append("\n\n".join(current_paras))
                
                # 🛡️ 核心修复：内联滑窗防重叠过滤
                potential_overlaps = current_paras[-1:] 
                safe_overlaps = []
                for overlap_p in potential_overlaps:
                    # 🚨 终极防线：覆盖全体系视觉锚点
                    if not any(kw in overlap_p for kw in ["🖼️", "[PENDING_IMG", "[AI_VISION_TARGET"]):
                        safe_overlaps.append(overlap_p)
                
                current_paras = safe_overlaps
                current_len = sum(len(cp) for cp in current_paras)
                
        if current_paras:
            if len(chunks) > 0 and current_len < (chunk_size // 2):
                chunks[-1] += "\n\n" + "\n\n".join(current_paras)
            else:
                chunks.append("\n\n".join(current_paras))

        # 2. 组装元数据并生成绝对防伪 ID
        source_name = meta.get("source", meta.get("kb_category", "TXT_Direct"))
        base_hash = meta.get("file_hash", "default_hash") 
        
        valid_chunks = []
        valid_metas = []
        
        for i, chunk in enumerate(chunks):
            chunk_meta = meta.copy()
            chunk_meta["chunk_index"] = i
            
            # 👑 修复：将主键指纹独立放入 chunk_hash 字段，保护 file_hash！
            unique_string = f"{source_name}_{base_hash}_chunk{i}_{chunk[:30]}"
            chunk_meta["chunk_hash"] = hashlib.sha256(unique_string.encode('utf-8')).hexdigest()
            
            valid_chunks.append(chunk)
            valid_metas.append(chunk_meta)

        print(f"\n🧩 [文档直通车自动切块] {source_name} 被智能划分为 {len(valid_chunks)} 个完美段落块。")
        return self.add_batches(valid_chunks, valid_metas)