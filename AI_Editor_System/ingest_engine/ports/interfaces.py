from abc import ABC, abstractmethod
from typing import List, Set
from ingest_engine.domain.schemas import VisualLedger

# ==========================================================
# 🔌 Ports (接口层)
# ----------------------------------------------------------
# 这里定义了核心模块必须遵守的契约。
# 上层编排逻辑(Orchestrator)只依赖这些接口，不依赖具体实现。
# ==========================================================

class IVisionProvider(ABC):
    """
    [视觉端口]
    负责将文件(PDF/Image)转化为结构化文本。
    """
    @abstractmethod
    def process(self, ledger: VisualLedger) -> VisualLedger:
        """
        接收一个账本，读取其中的 file_path，执行 OCR/VLM，
        填充 ledger.vision_result，最后返回更新后的账本。
        """
        pass

class IIngestRepository(ABC):
    """
    [存储端口]
    负责数据的持久化（Embedding + Vector DB）。
    """
    @abstractmethod
    def load_model(self):
        """懒加载 AI 模型"""
        pass

    @abstractmethod
    def get_existing_hashes(self) -> Set[str]:
        """获取已入库文件的哈希集合（用于增量更新）"""
        pass

    @abstractmethod
    def save(self, ledger: VisualLedger):
        """
        接收一个账本，将其 vision_result 向量化并存入数据库。
        更新 ledger.storage_record_id。
        """
        pass