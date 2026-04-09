import os
import sys
import json
import warnings
import gc
import math
import time
import io
import logging
import shutil
import re
from typing import Optional, List, Dict, Any, Tuple

# ==========================================================
# 🩹 NumPy 2.0 Compatibility Patch
# ==========================================================
def apply_numpy_patch():
    try:
        warnings.simplefilter(action='ignore', category=FutureWarning)
        import numpy as np
        if not hasattr(np, 'sctypes'):
            np.sctypes = {
                'int': [np.int8, np.int16, np.int32, np.int64],
                'uint': [np.uint8, np.uint16, np.uint32, np.uint64],
                'float': [np.float16, np.float32, np.float64],
                'complex': [np.complex64, np.complex128],
                'others': [bool, object, bytes, str, np.void]
            }
            if not hasattr(np, 'bool'): np.bool = np.bool_
            if not hasattr(np, 'int'): np.int = np.int64
            if not hasattr(np, 'float'): np.float = np.float64
            if not hasattr(np, 'object'): np.object = object
            if not hasattr(np, 'str'): np.str = np.str_
    except ImportError:
        pass

apply_numpy_patch()

os.environ["CUDA_VISIBLE_DEVICES"] = "" 
os.environ["FLAGS_use_gpu"] = "0"
os.environ["PADDLE_FORCE_CPU"] = "1"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import cv2
import numpy as np
import fitz  
from PIL import Image 

logger = logging.getLogger("ingest_engine.vision_core")

CV_AVAILABLE = False
try:
    import paddle
    paddle.set_device("cpu") 
    from paddleocr import PPStructure
    from openai import OpenAI
    CV_AVAILABLE = True
    logging.getLogger("ppocr").setLevel(logging.ERROR)
    logging.getLogger("paddle").setLevel(logging.ERROR)
except Exception:
    pass

try:
    from ingest_engine.config.settings import settings
    from ingest_engine.domain.schemas import VisualLedger, VisionMetadata
except ImportError: 
    pass

class ImageUtils:
    @staticmethod
    def sanitize_image(image_bytes: bytes) -> Optional[np.ndarray]:
        if not CV_AVAILABLE: return None
        try:
            nparr = np.frombuffer(image_bytes, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
            if image is None: return None
            MAX_PIXELS = 800000 
            h, w = image.shape[:2]
            pixels = h * w
            if pixels > MAX_PIXELS:
                scale = math.sqrt(MAX_PIXELS / pixels)
                new_w, new_h = int(w * scale), int(h * scale)
                image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_NEAREST)
            return image
        except Exception:
            return None

    @staticmethod
    def save_crop(image: np.ndarray, box: List[int], save_dir: str, name: str) -> str:
        try:
            x1, y1, x2, y2 = int(box[0]), int(box[1]), int(box[2]), int(box[3])
            h, w = image.shape[:2]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            if x2 - x1 < 50 or y2 - y1 < 50: return "" 
            crop = image[y1:y2, x1:x2]
            save_path = os.path.join(save_dir, name)
            cv2.imwrite(save_path, crop)
            return save_path
        except Exception:
            return ""

class DualTrackEngine:
    HANDLE_RESET_INTERVAL = 20 
    ENGINE_ROTATION_INTERVAL = 100 
    
    def __init__(self):
        self.layout_engine: Optional[PPStructure] = None
        self.vlm_client: Optional[OpenAI] = None
        self._vlm_model: str = "glm-4v-flash"
        try:
            output_dir = getattr(settings, 'output_dir', None)
        except NameError:
            output_dir = None
        if output_dir is None:
            output_dir = os.path.dirname(os.path.dirname(__file__))
        self.temp_dir = os.path.join(output_dir, "temp_assets")
        os.makedirs(self.temp_dir, exist_ok=True)
        self._initialize_engines = self._init_ocr_engine
    
    def _init_ocr_engine(self) -> None:
        if not CV_AVAILABLE: return
        self._unload_engine() 
        try:
            self.layout_engine = PPStructure(
                show_log=False, image_orientation=False, use_gpu=False,           
                lang='ch', enable_mkldnn=False, det_limit_side_len=736, det_limit_type='max'
            )
        except Exception: pass

    def _init_vlm_engine(self):
        try:
            zhipu_key = os.getenv("ZHIPU_API_KEY", "").strip()
            openai_key = os.getenv("OPENAI_API_KEY", "").strip()
            if zhipu_key:
                self.vlm_client = OpenAI(
                    api_key=zhipu_key,
                    base_url="https://open.bigmodel.cn/api/paas/v4/"
                )
                self._vlm_model = "glm-4v-flash"
            elif openai_key:
                self.vlm_client = OpenAI(api_key=openai_key)
                self._vlm_model = "gpt-4o"
        except Exception:
            pass

    def _unload_engine(self):
        if self.layout_engine:
            try: del self.layout_engine
            except: pass
            self.layout_engine = None
        gc.collect()

    def process(self, ledger: VisualLedger) -> VisualLedger:
        file_path = ledger.file_path
        ext = os.path.splitext(file_path)[1].lower()
        file_hash = ledger.file_hash[:8] 
        skip_images = getattr(ledger, 'skip_images', False)
        
        try:
            ocr_text = ""
            ver_tag = "Unknown"
            confidence = 0.0

            if ext == '.txt':
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        ocr_text = f.read()
                    ver_tag = "Text-Direct-Stream"
                    confidence = 1.0
                    logger.info(f"⚡ [纯文本直通车] 成功读取 TXT，共 {len(ocr_text)} 字符。")
                except Exception as e:
                    logger.error(f"读取 TXT 失败: {e}")
                    ocr_text = ""
            elif ext in ['.json', '.jsonl']:
                ocr_text = self._extract_json_content(file_path)
                ver_tag = "JSON-Direct"
                confidence = 0.99
            else:
                fast_text, img_count = self._extract_pdf_text_full(file_path)

                force_vision = False
                if len(fast_text.strip()) < 200:
                    force_vision = True
                elif not skip_images and img_count > 0:
                    force_vision = True
                    logger.info(f"📸 [视觉强制唤醒] 发现 {img_count} 张高价值插图，即将启动深度视觉解析...")

                if force_vision and CV_AVAILABLE:
                    asset_dir = os.path.join(self.temp_dir, file_hash)
                    if os.path.exists(asset_dir): shutil.rmtree(asset_dir)
                    os.makedirs(asset_dir, exist_ok=True)

                    self._init_ocr_engine()
                    ocr_text_with_placeholders = self._perform_ocr_stage(
                        file_path, asset_dir, skip_images=skip_images
                    )
                    
                    self._unload_engine()
                    time.sleep(1) 

                    if not skip_images and "[PENDING_IMG:" in ocr_text_with_placeholders:
                        self._init_vlm_engine()
                        final_text = self._perform_vlm_stage(ocr_text_with_placeholders)
                    else:
                        final_text = ocr_text_with_placeholders
                    
                    ocr_text = final_text
                    ver_tag = "Hybrid-Vision-Scan" + ("-TextOnly" if skip_images else "-VLM")
                    confidence = 0.95
                
                else:
                    ocr_text = fast_text
                    ver_tag = "Text-FastPass" if skip_images else "Text-Extract"
                    confidence = 0.90 if fast_text else 0.0                    
                    if img_count > 15 and not skip_images:
                        logger.warning(f"\n👁️‍🗨️ [Image Radar] 警报: {os.path.basename(file_path)}")
                        logger.warning(f"    -> 系统检测到该 PDF 包含 {img_count} 张插图。")
                        logger.warning(f"    -> 由于该文件未开启跳过特权，若非导演/摄影书籍，建议归入编剧库或手动提取。\n")
            
            if hasattr(ledger, 'vision_result'):
                ledger.vision_result = type(ledger.vision_result)(
                    ocr_text=ocr_text, 
                    engine_version=ver_tag
                ) if ledger.vision_result is not None else VisionMetadata(ocr_text=ocr_text, confidence_score=confidence, processing_time_ms=0.0, engine_version=ver_tag)
            
            if hasattr(ledger, 'log_step'):
                ledger.log_step("vision_process", "success")
            
        except Exception as e:
            logger.error(f"处理流程异常: {e}")
            if hasattr(ledger, 'log_step'):
                ledger.log_step("vision_process", "failure", str(e))
            
        return ledger

    def _extract_pdf_text_full(self, path: str) -> Tuple[str, int]:
        text_blocks = []
        image_count = 0
        try:
            with fitz.open(path) as doc:
                for page in doc:
                    t = page.get_text().strip()
                    if t: text_blocks.append(t)
                    img_list = page.get_images(full=True)
                    if img_list: image_count += len(img_list)
        except Exception: pass
        return "\n\n".join(text_blocks), image_count

    def _perform_ocr_stage(self, path: str, save_dir: str, skip_images: bool = False) -> str:
        full_text_list = []
        try:
            with fitz.open(path) as doc:
                total_pages = len(doc)
        except:
            return ""

        mode_str = "TextOnly" if skip_images else "Full"
        print(f"   [Stage1 OCR ({mode_str})]: ", end="", flush=True)

        for i in range(total_pages):
            if i > 0 and i % self.ENGINE_ROTATION_INTERVAL == 0:
                self._init_ocr_engine()
                gc.collect()

            page_success = False
            try:
                with fitz.open(path) as doc:
                    pix = doc[i].get_pixmap(dpi=150)
                    img_bytes = pix.tobytes("png")
                    del pix

                    processed_img = ImageUtils.sanitize_image(img_bytes)
                    del img_bytes

                    if processed_img is not None and self.layout_engine:
                        result = self.layout_engine(processed_img)
                        page_text = self._parse_and_save_assets(result, processed_img, save_dir, page_idx=i, skip_images=skip_images)
                        full_text_list.append(page_text)

                        del processed_img; del result
                    page_success = True
            except Exception:
                pass
            print("." if page_success else "x", end="", flush=True)
            if (i+1) % 20 == 0:
                gc.collect()
        print(" ✅", flush=True)
        return "\n\n".join(full_text_list)

    def _parse_and_save_assets(self, results: Any, image: np.ndarray, save_dir: str, page_idx: int, skip_images: bool) -> str:
        if not results: return ""
        all_regions = []
        if isinstance(results, list):
            for r in results:
                if isinstance(r, list): all_regions.extend(r)
                else: all_regions.append(r)
        
        all_regions.sort(key=lambda x: x.get('bbox', [0, 0, 0, 0])[1])
        text_buffer = []
        
        for idx, region in enumerate(all_regions):
            if not isinstance(region, dict): continue
            r_type = region.get('type', 'text')
            bbox = region.get('bbox', [])
            
            if r_type in ['figure', 'table']:
                if not skip_images:
                    img_name = f"p{page_idx}_r{idx}_{r_type}.jpg"
                    saved_path = ImageUtils.save_crop(image, bbox, save_dir, img_name)
                    if saved_path: text_buffer.append(f"\n>> [PENDING_IMG:{saved_path}] <<\n")
                
                res = region.get('res', [])
                for line in res:
                    if isinstance(line, dict): text_buffer.append(f"[Table/Fig Text]: {line.get('text', '')}")
            else:
                res = region.get('res', [])
                for line in res:
                    if isinstance(line, dict): text_buffer.append(line.get('text', ''))
        return "\n".join(text_buffer)

    def _perform_vlm_stage(self, text: str) -> str:
        print(f"   [Stage2 VLM]: ", end="", flush=True)
        pattern = r">> \[PENDING_IMG:(.*?)\] <<"
        matches = re.findall(pattern, text)
        if not matches: return text
        
        processed_text = text
        for idx, img_path in enumerate(matches):
            if os.path.exists(img_path):
                try:
                    # 🛡️ 智能填充视觉描述 (如开启 API，将真正调用)
                    description = "（视觉内容分析中...）"
                    if self.vlm_client:
                        try:
                            import base64
                            with open(img_path, "rb") as img_file:
                                base64_image = base64.b64encode(img_file.read()).decode('utf-8')
                            response = self.vlm_client.chat.completions.create(
                                model=self._vlm_model,
                                messages=[{"role": "user", "content": [{"type": "text", "text": "请解析这张图。"}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}],
                                max_tokens=150
                            )
                            description = response.choices[0].message.content.strip()
                        except: pass
                    
                    # 🛡️ 注入物理 ID 防伪指纹
                    img_filename = os.path.basename(img_path)
                    
                    processed_text = processed_text.replace(
                        f">> [PENDING_IMG:{img_path}] <<", 
                        f"\n> 🖼️ [AI视觉锚点 | 绑定ID: {img_filename}]: {description}\n"
                    )
                except Exception:
                    processed_text = processed_text.replace(f">> [PENDING_IMG:{img_path}] <<", "[图片读取失败]")

            print("v", end="", flush=True)
            if (idx+1) % 10 == 0: gc.collect()
        print(" ✅", flush=True)
        return processed_text

    def _extract_json_content(self, path: str) -> str:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                if path.endswith('.jsonl'):
                    lines = [json.loads(line) for line in f]
                    return "\n\n".join([json.dumps(obj, ensure_ascii=False) for obj in lines])
                data = json.load(f)
            if isinstance(data, list):
                buffer = []
                for idx, item in enumerate(data):
                    if isinstance(item, dict):
                        content = item.get("text") or item.get("content") or item.get("body")
                        if content: buffer.append(str(content))
                        else: buffer.append(json.dumps(item, ensure_ascii=False))
                    else: buffer.append(str(item))
                return "\n\n".join(buffer)
            return json.dumps(data, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"[Error Parsing JSON]: {e}"