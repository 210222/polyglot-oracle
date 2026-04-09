import logging
import os
import sys

# 1. 创建日志目录
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(log_dir, exist_ok=True)

# 2. 初始化模块级 Logger
logger = logging.getLogger("ingest_engine")
logger.setLevel(logging.INFO)

# 3. 防止重复添加 Handler (避免日志重复打印)
if not logger.handlers:
    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(name)s] - %(message)s', datefmt='%H:%M:%S')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # (可选) 文件输出
    # file_handler = logging.FileHandler(os.path.join(log_dir, "system.log"), encoding='utf-8')
    # file_handler.setFormatter(formatter)
    # logger.addHandler(file_handler)