# -*- coding: utf-8 -*-
"""
ue_bridge.py - Web UI → UE5 UDP 发送侧
职责：将 Polyglot Oracle 生成的 assets 列表序列化为 UDP 数据包，
      逐条发送至 ue_receiver.py 监听的端口。

设计原则：
- 纯同步，无事件循环依赖，可在 Streamlit 任意位置直接调用。
- 每次调用创建独立 socket（with 上下文管理器），发完即关，不持有长连接。
- 单包超过 UDP 安全上限（60000 字节）时自动截断并记录警告，不崩溃。
- UE5 未启动时 sendto 静默失败（OSError），由调用方决定是否展示错误。

端口约定：
  11111 → 生产端 ue_receiver.py（UE5 内部）
  11112 → 调试端 ue_link_debugger.py（本地终端验证）
"""
import socket
import json
import logging
from typing import List, Dict, Any, Tuple

logger = logging.getLogger("ue_bridge")

# 单包安全上限：UDP 理论上限 65535，减去 IP/UDP 头部留出余量
_UDP_MAX_BYTES = 60000


def send_assets_to_ue5(
    assets: List[Dict[str, Any]],
    host: str = "127.0.0.1",
    port: int = 11111,
) -> Tuple[int, List[str]]:
    """
    将 assets 列表逐条序列化并通过 UDP 发送至 UE5 接收端。

    参数:
        assets : Polyglot Oracle 返回的 assets 列表
        host   : 目标地址，默认本机
        port   : 目标端口，默认 11111（生产端）

    返回:
        (sent_count, errors)
        sent_count : 成功发出的包数
        errors     : 每条失败的错误描述列表（空列表代表全部成功）
    """
    sent_count = 0
    errors: List[str] = []

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(2.0)

        for idx, asset in enumerate(assets):
            # 构造符合 DLDO 协议的数据包结构
            packet = {
                "scene_id": asset.get("scene_id", f"SC_{idx:03d}"),
                "target_engine": asset.get("target_engine", "Unknown"),
                "generative_cornerstones": asset.get("generative_cornerstones", {}),
                "state_update": asset.get("state_update"),
                "production_assets": {
                    "ue5_params": _extract_ue5_params(asset),
                },
            }

            try:
                data = json.dumps(packet, ensure_ascii=False).encode("utf-8")

                if len(data) > _UDP_MAX_BYTES:
                    msg = (
                        f"Scene {packet['scene_id']}: packet {len(data)}B "
                        f"exceeds UDP safe limit ({_UDP_MAX_BYTES}B), send aborted."
                    )
                    logger.error(f"[UE Bridge] {msg}")
                    errors.append(msg)
                    continue

                sock.sendto(data, (host, port))
                sent_count += 1
                logger.info(
                    f"[UE Bridge] Sent scene {packet['scene_id']} "
                    f"({len(data)}B) → {host}:{port}"
                )

            except OSError as e:
                msg = f"Scene {packet['scene_id']}: sendto failed ({e})"
                logger.warning(f"[UE Bridge] {msg}")
                errors.append(msg)
            except Exception as e:
                msg = f"Scene {packet['scene_id']}: unexpected error ({e})"
                logger.error(f"[UE Bridge] {msg}")
                errors.append(msg)

    return sent_count, errors


def _extract_ue5_params(asset: Dict[str, Any]) -> Dict[str, Any]:
    """
    从 asset 的 generative_cornerstones 中提取可直接映射到 UE5 Actor 属性的参数。
    ue_receiver.py 的 apply_ai_assets() 读取 production_assets.ue5_params 字段。

    当前提取逻辑：从 i2v_prompt 中解析焦距关键词作为示例参数注入。
    后续可扩展为从 meta_data 或专用字段读取结构化参数。
    """
    gc = asset.get("generative_cornerstones", {})
    meta = asset.get("meta_data", {})

    ue5_params: Dict[str, Any] = {}

    # 引擎名透传，供 UE5 侧做条件分支
    engine = asset.get("target_engine", meta.get("engine_used", ""))
    if engine:
        ue5_params["engine"] = engine

    # 情绪状态透传（可驱动 UE5 后期处理材质参数）
    narrative = asset.get("narrative_analysis", {})
    if narrative.get("emotional_register"):
        ue5_params["emotional_register"] = narrative["emotional_register"]

    # 焦距关键词映射（示例：供 CineCameraActor 使用）
    i2v = gc.get("i2v_prompt", "").lower()
    if "wide" in i2v or "wide angle" in i2v:
        ue5_params["focal_length"] = 24.0
    elif "telephoto" in i2v or "85mm" in i2v:
        ue5_params["focal_length"] = 85.0
    elif "macro" in i2v or "close-up" in i2v:
        ue5_params["focal_length"] = 100.0

    # 灯光强度关键词映射（示例：供 Light Actor 使用）
    if "golden hour" in i2v or "warm light" in i2v:
        ue5_params["intensity"] = 8.0
        ue5_params["color_temp"] = 4500
    elif "neon" in i2v or "blue light" in i2v:
        ue5_params["intensity"] = 5.0
        ue5_params["color_temp"] = 6500

    return ue5_params
