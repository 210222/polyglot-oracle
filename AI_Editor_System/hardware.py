# -*- coding: utf-8 -*-
# hardware.py - GPU 状态检测（纯 torch，无 LLM 依赖）
# 独立模块，避免 web_ui.py 因 get_gpu_status 而拉起 services.py 的 LLMService 单例。
def get_gpu_status() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            vram = torch.cuda.get_device_properties(0).total_memory / 1e9
            return f"🟢 GPU Online: {torch.cuda.get_device_name(0)} ({vram:.1f}GB)"
        return "⚪ CPU Mode (Neural Engine Limited)"
    except Exception:
        return "⚪ CPU Mode (torch not available)"
