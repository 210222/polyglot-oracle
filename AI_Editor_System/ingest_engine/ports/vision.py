import os
import sys
import warnings
from pathlib import Path

# ==========================================================
# 🚨 绝对防御 & 显存节流阀
# ==========================================================
def _setup_paddle_environment() -> None:
    """配置Paddle运行环境，专治显存溢出"""
    
    # 1. 显存节流阀 (针对 RTX 2060 6G 用户的核心补丁)
    # 强制将初始显存申请限制在 500MB，防止 8000MB 暴食导致崩溃
    os.environ["FLAGS_initial_gpu_memory_in_mb"] = "500"
    os.environ["FLAGS_gpu_memory_mb"] = "500" 
    os.environ["FLAGS_fraction_of_gpu_memory_to_use"] = "0.1" # 只允许使用 10%
    
    # 2. 核心隔离 (CPU优先策略)
    # 如果您想尝试用GPU，可以注释掉下面这行 CUDA_VISIBLE_DEVICES
    os.environ["CUDA_VISIBLE_DEVICES"] = "" 
    os.environ["FLAGS_use_gpu"] = "0"
    os.environ["PADDLE_FORCE_CPU"] = "1"
    
    # 3. 日志与兼容性
    os.environ["GLOG_v"] = "3"  # 闭嘴模式
    os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

_setup_paddle_environment()

# ==========================================================
# 标准库导入
# ==========================================================
import cv2
import numpy as np
import logging
import functools
import fitz  # PyMuPDF
from typing import Optional, List, Dict, Any

# ==========================================================
# Paddle 软加载
# ==========================================================
try:
    import paddle
    # 双重保险：在 Python 层再次限制设备
    if os.environ.get("CUDA_VISIBLE_DEVICES") == "":
        paddle.set_device("cpu")
except ImportError:
    pass
except Exception as e:
    warnings.warn(f"Paddle 设置警告: {e}")

# ==========================================================
# 依赖检测
# ==========================================================
CV_AVAILABLE = False
try:
    from paddleocr import PPStructure
    from openai import OpenAI
    CV_AVAILABLE = True
    logging.getLogger("ppocr").setLevel(logging.WARNING)
    logging.getLogger("paddle").setLevel(logging.WARNING)
except ImportError as e:
    logging.warning(f"⚠️ 视觉模块依赖缺失: {e}")
except Exception as e:
    logging.warning(f"⚠️ 视觉模块加载异常: {e}")

# ==========================================================
# 本地模块导入
# ==========================================================
try:
    from ingest_engine.config.settings import settings
    from ingest_engine.domain.schemas import VisualLedger, VisionMetadata
    from ingest_engine.ports.interfaces import IVisionProvider
except ImportError:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.dirname(current_dir))
    from ingest_engine.config.settings import settings
    from ingest_engine.domain.schemas import VisualLedger, VisionMetadata
    from ingest_engine.ports.interfaces import IVisionProvider

logger = logging.getLogger("ingest_engine.vision")


class ImageUtils:
    """图像处理工具箱"""
    
    @staticmethod
    @functools.lru_cache(maxsize=128)
    def deskew(image_bytes: bytes) -> bytes:
        """图像去偏斜"""
        if not CV_AVAILABLE: return image_bytes
        try:
            nparr = np.frombuffer(image_bytes, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if image is None: return image_bytes
            
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            gray = cv2.bitwise_not(gray)
            thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
            coords = np.column_stack(np.where(thresh > 0)[::-1])
            if coords.size == 0: return image_bytes
            
            angle = cv2.minAreaRect(coords)[-1]
            if angle < -45: angle = -(90 + angle)
            else: angle = -angle
            
            if abs(angle) > 5.0 or abs(angle) < 0.1: return image_bytes
            
            (h, w) = image.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            result = cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
            _, buffer = cv2.imencode('.jpg', result)
            return buffer.tobytes()
        except Exception:
            return image_bytes

    @staticmethod
    def enhance_contrast(image_bytes: bytes) -> Optional[np.ndarray]:
        if not CV_AVAILABLE: return None
        try:
            nparr = np.frombuffer(image_bytes, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if image is None: return None
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            gray = cv2.fastNlMeansDenoising(gray, h=3)
            binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
            return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        except Exception:
            return None


class DualTrackEngine(IVisionProvider):
    """
    [核心适配器] 智能感知版
    """
    
    def __init__(self):
        self.vlm_client: Optional[OpenAI] = None
        self.layout_engine: Optional[PPStructure] = None
        self._initialize_engines()
    
    def _check_pulc_model_exists(self) -> bool:
        """侦测 PULC 模型文件是否存在"""
        try:
            # PaddleClas 默认存储路径
            home = Path.home()
            model_path = home / ".paddleclas" / "inference_model" / "PULC" / "text_image_orientation" / "inference.pdmodel"
            exists = model_path.exists()
            if exists:
                logger.info(f"🕵️ 发现本地方向矫正模型: {model_path}")
            else:
                logger.info(f"🕵️ 未检测到本地模型 (路径: {model_path})，将自动关闭方向矫正以防崩溃")
            return exists
        except Exception:
            return False

    def _initialize_engines(self) -> None:
        """初始化视觉引擎 (带显存保护和智能降级)"""
        if not CV_AVAILABLE:
            logger.warning("⚠️ 视觉模块不可用")
            return
        
        # 即使这里是 False，底层的 FLAGS_initial_gpu_memory_in_mb 也会保护显存不溢出
        use_gpu = False 
        
        # 智能开关：只有当您下载了模型文件，这里才会是 True
        enable_orientation = self._check_pulc_model_exists()

        try:
            logger.info(f"🚀 初始化 PaddleOCR (方向矫正: {'✅开启' if enable_orientation else '⬜关闭'})...")
            
            self.layout_engine = PPStructure(
                show_log=False, 
                image_orientation=enable_orientation, # 👈 根据文件存在与否自动决定
                use_gpu=use_gpu, 
                **{"use_gpu": False}
            )
            logger.info("✅ PaddleOCR 引擎就绪")
            self._init_vlm_client()

        except Exception as e:
            logger.error(f"❌ 初始化严重失败: {e}")
            # 最后的防线：如果还是挂了，彻底关闭 OCR
            self.layout_engine = None
    
    def _init_vlm_client(self) -> None:
        if not settings.vision.enable_vlm: return
        try:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key: return
            self.vlm_client = OpenAI(api_key=api_key)
            logger.info("✅ VLM 已连接")
        except Exception: pass

    def process(self, ledger: VisualLedger) -> VisualLedger:
        file_path = ledger.file_path
        try:
            text_content = self._extract_pdf_text(file_path)
            
            # 当文本过少时触发 OCR
            if len(text_content.strip()) < 50 and self.layout_engine:
                logger.info(f"👁️ 触发OCR增强: {os.path.basename(file_path)}")
                ocr_text = self._perform_ocr(file_path)
                if len(ocr_text) > len(text_content):
                    text_content = ocr_text
                    ledger.log_step("ocr_fallback", "success", "PaddleOCR Active")
            
            ledger.vision_result = VisionMetadata(
                ocr_text=text_content,
                confidence_score=0.95 if text_content else 0.0,
                processing_time_ms=0.0,
                engine_version="DT-v11-2060Fix"
            )
        except Exception as e:
            logger.error(f"Vision Error: {e}")
            ledger.log_step("vision_process", "failure", str(e))
            
        return ledger

    def _extract_pdf_text(self, path: str) -> str:
        text = ""
        try:
            with fitz.open(path) as doc:
                for page in doc: text += page.get_text()
        except Exception: pass
        return text

    def _perform_ocr(self, path: str) -> str:
        full_text = []
        try:
            with fitz.open(path) as doc:
                for i in range(min(len(doc), 20)):
                    pix = doc[i].get_pixmap(dpi=150)
                    img_bytes = pix.tobytes("png")
                    
                    deskewed = ImageUtils.deskew(img_bytes)
                    enhanced = ImageUtils.enhance_contrast(deskewed)
                    if enhanced is None: continue
                    
                    # 核心推理
                    results = self.layout_engine(enhanced)
                    full_text.append(self._parse_paddle_result(results))
        except Exception as e:
            logger.error(f"OCR执行错误: {e}")
        return "\n".join(full_text)

    def _parse_paddle_result(self, results: List[Dict[str, Any]]) -> str:
        text_buffer = []
        if not results: return ""
        
        # 展平结构
        regions = []
        for r in results:
            if isinstance(r, list): regions.extend(r)
            else: regions.append(r)
            
        for region in regions:
            r_type = region.get('type', 'text')
            if r_type in ['header', 'footer']: continue
            
            res = region.get('res', [])
            line = " ".join([l.get('text', '') for l in res])
            
            if r_type == 'table': text_buffer.append(f"\n[TABLE]\n{line}\n")
            elif r_type == 'figure': text_buffer.append(f"\n[FIGURE] {line}\n")
            else: text_buffer.append(line)
            
        return "\n".join(text_buffer)