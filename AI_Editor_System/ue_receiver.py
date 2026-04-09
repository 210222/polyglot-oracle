# -*- coding: utf-8 -*-
"""
ue_receiver.py - UE5 内部 UDP 接收端
运行环境：UE5 内置 Python 解释器 (unreal 模块可用)
监听端口：11111 （生产端口，仅供 Web UI 发包使用）

修复 C-3：
- 使用 with socket.socket(...) as sock 上下文管理器，
  保证线程退出或异常时 sock 立即关闭，端口瞬间释放。
- 引入 _stop_event 退出信号，支持从外部优雅终止监听循环。
- sock.settimeout(1.0)：recvfrom 不再永久阻塞，每秒检查一次退出信号。
- 缓冲区从 4096 扩大到 65535，防止多镜头 JSON 大包被静默截断。
"""
import socket
import json
import threading
import unreal

# 生产端口：与 Web UI 发送侧保持一致，调试器使用独立的 11112 端口
UDP_HOST = "127.0.0.1"
UDP_PORT = 11111
RECV_BUF = 65535  # 防大包截断

# 外部可调用 _stop_event.set() 来优雅终止监听线程
_stop_event = threading.Event()


def apply_ai_assets(data):
    """
    核心映射逻辑：根据 DLDO 协议将参数注入 UE5 Actor
    """
    ue_params = data.get("production_assets", {}).get("ue5_params", {})
    scene_id = data.get("scene_id", "Unknown_Scene")

    tagged_actors = unreal.EditorLevelLibrary.get_all_level_actors()

    for actor in tagged_actors:
        if actor.actor_has_tag("AI_Controlled"):
            unreal.log(f"AI Engine: Updating Actor {actor.get_name()} for {scene_id}")

            if isinstance(actor, unreal.CineCameraActor):
                cam_comp = actor.get_cine_camera_component()
                if "focal_length" in ue_params:
                    cam_comp.set_editor_property("current_focal_length", ue_params["focal_length"])

            elif isinstance(actor, unreal.Light):
                # unreal.Light 是抽象基类，属性挂载在 LightComponent 上，不在 Actor 本体
                light_comp = actor.get_component_by_class(unreal.LightComponent)
                if light_comp:
                    if "intensity" in ue_params:
                        light_comp.set_editor_property("intensity", ue_params["intensity"])
                    if "color_temp" in ue_params:
                        light_comp.set_editor_property("temperature", ue_params["color_temp"])


def start_udp_listener():
    """
    建立 UDP 网桥，监听来自 Web UI 的指令。
    使用 with 上下文管理器确保 sock 在任何退出路径上都能关闭。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)  # 非永久阻塞，每秒轮询一次退出信号
        sock.bind((UDP_HOST, UDP_PORT))
        unreal.log(f"UDP Listener bound to {UDP_HOST}:{UDP_PORT}")

        while not _stop_event.is_set():
            try:
                raw_data, addr = sock.recvfrom(RECV_BUF)
                payload = json.loads(raw_data.decode("utf-8"))
                # 必须在主线程执行 UE 属性修改操作
                unreal.asynchronous_main_frame_run(apply_ai_assets, [payload])
            except socket.timeout:
                # 正常超时，继续检查 _stop_event
                continue
            except json.JSONDecodeError as e:
                unreal.log_error(f"UDP bad payload (JSONDecodeError): {e}")
            except Exception as e:
                unreal.log_error(f"UDP Link Error: {e}")

    unreal.log("UDP Listener stopped, port released.")


# 启动守护线程，避免阻塞 UE5 编辑器渲染
# 防热重载守卫：若同名线程已存活（模块被重新 import），先优雅停止旧线程再重启，
# 避免 SO_REUSEADDR 下多 socket 竞争同一端口导致 UDP 包随机分流。
_THREAD_NAME = "ue_udp_listener"

_existing = next(
    (t for t in threading.enumerate() if t.name == _THREAD_NAME and t.is_alive()),
    None
)
if _existing:
    _stop_event.set()           # 通知旧线程退出（recvfrom timeout=1.0，至多等 1s）
    _existing.join(timeout=2.0) # 等旧线程释放端口
    _stop_event.clear()         # 重置信号，供新线程使用

thread = threading.Thread(target=start_udp_listener, name=_THREAD_NAME, daemon=True)
thread.start()
unreal.log(f"UDP listener thread started (name={_THREAD_NAME}, pid={thread.ident})")
