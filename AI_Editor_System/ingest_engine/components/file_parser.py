import os
import logging
from typing import List, Set

logger = logging.getLogger("ingest_engine.file_parser")

class FileCrawler:
    """
    文件扫描器
    [Update]: 新增对 .json 和 .jsonl 文件的支持
    """
    def __init__(self, root_dir: str, blacklist: Set[str]):
        self.root_dir = root_dir
        self.blacklist = blacklist
        # 新增 .json, .jsonl 支持
        self.supported_exts = {'.pdf', '.txt', '.md', '.json', '.jsonl'}

    def scan(self) -> List[str]:
        if not os.path.exists(self.root_dir):
            logger.warning(f"目录不存在: {self.root_dir}，尝试创建...")
            os.makedirs(self.root_dir, exist_ok=True)
            return []

        target_files = []
        for root, dirs, files in os.walk(self.root_dir):
            for file in files:
                if file in self.blacklist:
                    continue
                
                ext = os.path.splitext(file)[1].lower()
                if ext in self.supported_exts:
                    full_path = os.path.join(root, file)
                    target_files.append(full_path)
        
        return target_files