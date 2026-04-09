from pydantic import BaseModel, Field, ConfigDict, UUID4
from typing import List, Optional, Dict, Any, Literal
from datetime import datetime, timezone
import uuid

# ==========================================================
# 📒 The Visual Ledger (视觉账本)
# ----------------------------------------------------------
# 这是一个在管道中流动的"状态对象"。
# 它解耦了视觉处理(Vision Core)和数据存储(DB Adapter)。
# ==========================================================

class VisionMetadata(BaseModel):
    """
    视觉元数据：封装 Vision Core (OCR/VLM) 的原始输出。
    这是 Vision Core 向下游承诺交付的数据契约。
    """
    ocr_text: str = Field(..., description="OCR或VLM提取的原始文本内容")
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0, description="置信度")
    processing_time_ms: float = Field(default=0.0, description="处理耗时(毫秒)")
    engine_version: str = Field(default="v11.0", description="使用的引擎版本")
    
    # 灵活容器，用于存放布局信息、BBox等算法特定的数据
    # 允许算法升级而不破坏 Schema
    layout_data: Dict[str, Any] = Field(default_factory=dict) 

class IngestStatus(BaseModel):
    """不可变的步骤记录，用于审计和调试"""
    step_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Literal["success", "failure", "warning", "pending"]
    details: Optional[str] = None

class VisualLedger(BaseModel):
    """
    🏆 核心领域对象：Visual Ledger (视觉账本)
    
    它不仅是数据容器，还是整个入库流程的"记忆"。
    如果流程崩溃，Dump 这个对象就能完美复现现场。
    """
    id: UUID4 = Field(default_factory=uuid.uuid4)
    file_path: str = Field(..., description="源文件绝对路径")
    file_hash: str = Field(..., description="文件内容哈希，用于去重")
    kb_category: str = Field(default="shared_common", description="路由分类")
    
    # 历史记录 (自我审计能力)
    history: List[IngestStatus] = Field(default_factory=list)
    
    # 组件状态插槽 (Component State Slots)
    # 初始为 None，随着管道流动被填充
    vision_result: Optional[VisionMetadata] = None
    storage_record_id: Optional[str] = None
    
    # Pydantic 配置
    model_config = ConfigDict(from_attributes=True, validate_assignment=True)

    def log_step(self, step: str, status: str, details: str = None):
        """记录处理步骤"""
        self.history.append(IngestStatus(step_name=step, status=status, details=details))

    @property
    def is_processed(self) -> bool:
        """判断是否已完成视觉处理"""
        return self.vision_result is not None