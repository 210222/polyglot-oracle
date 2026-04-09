import logging
import json
import uuid
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Dict, Any

# --------------------------
# 自定义JSON日志格式化器
# --------------------------
class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "thread_id": record.thread,
            "process_id": record.process
        }
        # 全链路追踪字段
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        if hasattr(record, "task_type"):
            log_data["task_type"] = record.task_type
        if hasattr(record, "latency"):
            log_data["latency"] = record.latency
        if hasattr(record, "error_detail"):
            log_data["error_detail"] = record.error_detail
        if hasattr(record, "coze_response_code"):
            log_data["coze_response_code"] = record.coze_response_code
        # 异常栈信息
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data, ensure_ascii=False)

# --------------------------
# 全局日志器初始化
# --------------------------
def init_logger(logger_name: str = "ai_editor", log_file: str = "ai_editor.log", log_level: int = logging.INFO):
    logger = logging.getLogger(logger_name)
    logger.setLevel(log_level)
    logger.handlers.clear()
    
    # 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(JSONFormatter())
    logger.addHandler(console_handler)
    
    # 文件输出（自动轮转）
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=30,
        encoding="utf-8"
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(JSONFormatter())
    logger.addHandler(file_handler)
    return logger

# --------------------------
# 全局日志实例（默认初始化）
# --------------------------
logger = init_logger()

# --------------------------
# 业务日志工具函数
# --------------------------
def log_request(request_id: str, user_id: str, task_type: str, text: str):
    logger.info(
        "请求开始",
        extra={
            "request_id": request_id,
            "user_id": user_id,
            "task_type": task_type,
            "text_length": len(text)
        }
    )

def log_response(request_id: str, user_id: str, task_type: str, latency: float, success: bool, coze_code: int = None):
    logger.info(
        "请求结束",
        extra={
            "request_id": request_id,
            "user_id": user_id,
            "task_type": task_type,
            "latency": round(latency, 2),
            "success": success,
            "coze_response_code": coze_code
        }
    )

def log_error(request_id: str, user_id: str, task_type: str, error_msg: str, error_detail: str = None):
    logger.error(
        f"请求失败: {error_msg}",
        extra={
            "request_id": request_id,
            "user_id": user_id,
            "task_type": task_type,
            "error_detail": error_detail
        }
    )

# --------------------------
# 生成唯一请求ID（全链路追踪）
# --------------------------
def generate_request_id() -> str:
    return str(uuid.uuid4())