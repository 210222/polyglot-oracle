import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any
from dotenv import load_dotenv

# 加载 AI_Editor_System/.env，使 CHROMA_DB_PATH 等环境变量在 dataclass 默认值求值前生效
_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_FILE, override=True)

# 获取项目的绝对根目录
BASE_DIR = Path(__file__).resolve().parent.parent.parent

_default_chroma_dir = os.getenv(
    "CHROMA_DB_PATH",
    str(BASE_DIR / "data" / "vector_store")
)

@dataclass
class DatabaseSettings:
    """向量数据库与持久化配置"""
    cool_down: float = 2.0  # 写入冷却时间，防止高频 Chunk 插入导致 SSD I/O 阻塞
    chroma_persist_dir: str = _default_chroma_dir
    collection_name: str = "ai_editor_knowledge"
    
@dataclass
class AIEngineSettings:
    """
    AI Editor 生图/生视频多引擎架构支持 (Multi-Engine Support)
    """
    # 基础视觉与文本解析模型
    vision_model: str = "gpt-4o"
    embedding_model: str = "text-embedding-3-small"
    
    # 视频引擎挂载目标 (支持动态路由至 Kling, Hailuo, Luma, Veo)
    default_video_engine: str = "Kling"  # 默认偏向物理引擎 (Physics)
    
    # 生图引擎挂载目标
    default_image_engine: str = "Jimeng" # 即梦 (Jimeng) 接口预留
    
    # Unreal Engine 5 (UE5) 最终可视化与渲染对接
    ue5_python_api_enabled: bool = True
    ue5_project_path: str = os.path.join(BASE_DIR, "UE_Assets")

@dataclass
class GlobalSettings:
    """
    全局核心配置中枢 (Singleton)
    完全适配 pipeline.py 中的所有点语法调用
    """
    # --- 基础路径与 I/O 配置 ---
    kb_base_path: str = "Knowledge_Base"
    output_dir: str = os.path.join(BASE_DIR, "data", "processed")
    blacklist_files: List[str] = field(default_factory=lambda: [".DS_Store", "Thumbs.db", "~$", ".tmp"])

    # --- 分时复用架构 (TDM) 与 内存防护 ---
    memory_threshold_percent: float = 85.0
    batch_size: int = 5

    # --- 智能分类关键字 (Keyword-based) ---
    # 🚀 经过严密升级的雷达词典：精准识别中英文、专业术语及物理文件夹名
    category_keywords: Dict[str, List[str]] = field(default_factory=lambda: {
        "screenplay_expert": [
            "编剧", "剧本", "故事", "台词", 
            "screenplay", "01_screenplay"
        ],
        "director_expert": [
            "导演", "摄影", "分镜", "打光", "运镜", "视觉", 
            "director", "camera", "lighting", "photo", "visual language", "02_director"
        ],
        "axiom_rules": [
            "审查", "广电", "规章", "法", "censorship", "rule"
        ],
        "shared_common": [
            "通用", "法规", "general", "common"
        ]
    })

    # --- 特权直通车配置 (Privilege Pass) ---
    screenplay_privilege: Dict[str, bool] = field(default_factory=lambda: {
        "skip_image_extraction": True,   # 强制跳过图片提取，极大节省 16GB 内存压力
        "disable_circuit_breaker": True, # 不受 200 页大文件熔断限制，长剧本直通
	"skip_image_extraction": True      # 👈 加上这行最关键的开关！强行跳过看图！
    })

    # --- 普通库标准限制 ---
    standard_limits: Dict[str, Any] = field(default_factory=lambda: {
        "max_pages": 200,                # 超过 200 页触发 pipeline 中的大文件熔断
        "extract_images": True           # 导演库等默认允许抽取视觉参考图
    })

    # --- 嵌套子模块配置 ---
    db: DatabaseSettings = field(default_factory=DatabaseSettings)
    ai_engine: AIEngineSettings = field(default_factory=AIEngineSettings)

# 实例化全局单例，供整个系统 (如 pipeline.py) 直接 import settings
settings = GlobalSettings()