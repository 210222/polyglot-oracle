import threading
import logging
import hashlib
import os

class PerfCounter:
    """
    线程安全的性能计数器
    用于统计处理了多少文件、成功多少、失败多少。
    """
    def __init__(self):
        self._stats = {
            "processed": 0, 
            "success": 0, 
            "failed": 0, 
            "skipped": 0, 
            "ocr_triggered": 0
        }
        self._lock = threading.Lock()
    
    def inc(self, key: str, value: int = 1):
        with self._lock:
            self._stats[key] = self._stats.get(key, 0) + value
    
    def report(self) -> dict:
        return self._stats.copy()

def calculate_file_hash(file_path: str) -> str:
    """计算文件内容的 MD5 哈希"""
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception:
        return "unknown_hash"

def get_routing_category(file_path: str) -> str:
    """
    智能路由策略：根据文件名决定存入哪个知识库。
    """
    path_lower = file_path.lower().replace('\\', '/')
    fname_lower = os.path.basename(file_path).lower()
    
    sc = ['编剧', '故事', '人物', '对白', '剧本', '写作', 'screenplay', 'writer', 'story', 'script', 'save the cat']
    di = ['导演', '视觉', '镜头', '分镜', '摄影', '光影', 'director', 'shot', 'visual', 'ue5', 'camera', 'light']
    
    if any(k in path_lower or k in fname_lower for k in sc): return "screenplay_expert"
    if any(k in path_lower or k in fname_lower for k in di): return "director_expert"
    return "shared_common"