# -*- coding: utf-8 -*-
"""
ue_link_debugger.py - 本地 UE5 链路调试模拟器
运行环境：普通 Python 终端（不依赖 unreal 模块）
监听端口：11112 （调试专用端口，与生产端口 11111 完全隔离）

修复端口冲突 & socket 泄漏：
- 端口从 11111 改为 11112，彻底消除与 ue_receiver.py 的端口争抢。
- 使用 with socket.socket(...) as sock 上下文管理器，
  Ctrl+C 或任何异常退出时 sock 立即关闭，端口瞬间释放。
- sock.settimeout(1.0)：recvfrom 不再永久阻塞，支持 KeyboardInterrupt 响应。
- 缓冲区从 4096 扩大到 65535，防止多镜头 JSON 大包被静默截断。
"""
import socket
import json
from datetime import datetime

# 调试专用端口：与生产端 ue_receiver.py (11111) 完全隔离
UDP_IP   = "127.0.0.1"
UDP_PORT = 11112
RECV_BUF = 65535  # 防大包截断


def start_simulator():
    print(f"AI Engine - UE5 Link Simulator Online")
    print(f"Listening on {UDP_IP}:{UDP_PORT}  (debug port, production=11111)")
    print("-" * 50)

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)  # 非永久阻塞，支持 Ctrl+C 干净退出
        sock.bind((UDP_IP, UDP_PORT))

        while True:
            try:
                data, addr = sock.recvfrom(RECV_BUF)
            except socket.timeout:
                continue  # 正常超时，继续等待
            except KeyboardInterrupt:
                print("\nSimulator stopped, port released.")
                break

            ts = datetime.now().strftime("%H:%M:%S")
            try:
                payload    = json.loads(data.decode("utf-8"))
                scene_id   = payload.get("scene_id", "UNKNOWN")
                ue_params  = payload.get("production_assets", {}).get("ue5_params", {})

                print(f"[{ts}] Received Packet from {addr}")
                print(f"Scene ID  : {scene_id}")
                print(f"UE5 Params: {json.dumps(ue_params, indent=4, ensure_ascii=False)}")

                if not ue_params:
                    print("Warning: No UE5 parameters detected in production_assets!")
                else:
                    print("Data Integrity: OK")

            except json.JSONDecodeError as e:
                print(f"[{ts}] Error decoding packet: {e}")

            print("-" * 50)


if __name__ == "__main__":
    start_simulator()
