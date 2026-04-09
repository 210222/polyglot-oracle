# ==========================================================
# 注意：import torch 已从顶层移除。
# KMP_DUPLICATE_LIB_OK 环境变量在需要 torch 的 Stage 2 入口处设置，
# 避免选择 Stage 1 (CPU OCR) 时预占 CUDA 显存。
# ==========================================================
import os

import sys
import time
import traceback
from typing import NoReturn

# ==========================================================
# 🔧 环境引导
# ==========================================================
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_banner():
    print(r"""
    ================================================================
      AI Editor - Ingestion Control Center (SSP v12.1 拖拽入库版)
      Target: Hasee Z8 (i7-9750H / 16GB / RTX 2060 6GB)
    ================================================================
    """)

def main() -> NoReturn:
    while True:
        clear_screen()
        print_banner()
        
        print("请选择执行模式 (分时复用以保护显存):")
        print("----------------------------------------------------------------")
        print("  [1] 🟢 启动 Stage 1: CPU OCR 提取 (不占显存)")
        print("      -> 依赖: PaddleOCR (纯 CPU 模式)")
        print("")
        print("  [2] 🔴 启动 Stage 2: GPU VLM 视觉理解 (显存满载)")
        print("      -> 依赖: PyTorch, Qwen2-VL")
        print("")
        print("  [3] 🔵 启动 Stage 3: Embedding 入库 (分类模式)")
        print("      -> 依赖: ChromaDB, BGE-Small (双核)")
        print("")
        print("  [4] 🚀 自动收尾流水线 (全自动智能路由 + 拖拽单点入库)")
        print("      -> 包含: 视觉提取 + 智能切块 + 本地向量入库")
        print("----------------------------------------------------------------")
        print("  [Q] 退出")
        print("----------------------------------------------------------------")
        
        choice = input("\n请选择任务 ID [1-4/Q]: ").strip().upper()

        if choice == '1':
            clear_screen()
            print("🟢 启动 Stage 1: CPU OCR 提取")
            print("💡 提示: 您可以直接把文件或文件夹拖拽到这个窗口里")
            target_input = input("👉 请输入目标路径 (直接回车则使用默认配置): ").strip()
            target_input = target_input.strip('"').strip("'")
            
            try:
                from ingest_engine.stages import stage1_ocr
                if target_input:
                    stage1_ocr.run(target_path=target_input)
                else:
                    stage1_ocr.run()
                input("\n✅ Stage 1 完成。按回车键返回主菜单...")
            except ImportError as e:
                print(f"❌ 模块加载失败: {e}")
                time.sleep(3)
            except Exception as e:
                print(f"❌ 运行错误: {e}")
                time.sleep(3)

        elif choice == '2':
            clear_screen()
            try:
                # 懒加载 torch：仅在进入 Stage 2 时才占用 CUDA 显存
                import os as _os
                _os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
                import torch  # noqa: F401 — 触发 DLL 注册，防止后续 Paddle/Chroma 冲突
                from ingest_engine.stages import stage2_vlm
                stage2_vlm.run()
                input("\n✅ Stage 2 完成。按回车键返回主菜单...")
            except OSError as e:
                print(f"\n❌ PyTorch 环境错误 (DLL 缺失): {e}")
                input("\n按回车键返回...")
            except ImportError as e:
                print(f"❌ 模块加载失败: {e}")
                time.sleep(3)
            except Exception as e:
                # CUDA OOM / RuntimeError / 模型崩溃等 OSError+ImportError 未覆盖的场景
                # 对齐 Stage 4 的 except Exception 防御模式，防止崩溃穿透主进程
                print(f"❌ 运行错误 (CUDA OOM / 模型崩溃): {e}")
                traceback.print_exc()
                input("\n按回车键返回...")
            finally:
                # 恢复环境变量，避免污染后续 Stage（对齐 Stage 4 的 FLAGS_use_gpu 清理模式）
                # 使用模块级 os 而非 try 块内的 _os，保证 import 失败时 finally 也能执行
                os.environ.pop("KMP_DUPLICATE_LIB_OK", None)

        elif choice == '3':
            clear_screen()
            try:
                from ingest_engine.stages import stage3_embed
                stage3_embed.run()
                input("\n✅ Stage 3 完成。按回车键返回主菜单...")
            except Exception as e:
                print(f"❌ 运行错误: {e}")
                time.sleep(3)

        elif choice == '4':
            clear_screen()
            print("🚀 启动自动收尾流水线 (Smart Cleanup)...")
            print("💡 提示: 您可以直接把 PDF/TXT 文件或文件夹拖拽到这个窗口里")
            target_input = input("👉 请输入目标路径 (直接回车则扫描整个 Knowledge_Base): ").strip()
            target_input = target_input.strip('"').strip("'")
            
            try:
                # 强制 PaddleOCR 走 CPU
                os.environ["FLAGS_use_gpu"] = "0"

                from ingest_engine.pipeline import IngestionPipeline
                # 🎯 把你刚才输入的路径喂给流水线
                pipeline = IngestionPipeline(target_path=target_input if target_input else None)
                pipeline.run()

            except Exception as e:
                print(f"\n❌ 运行出错: {e}")
                traceback.print_exc()
            finally:
                # 恢复环境变量，避免污染本进程后续选择的 Stage 2（GPU 模式）
                os.environ.pop("FLAGS_use_gpu", None)
            input("\n按回车键返回主菜单...")

        elif choice == 'Q':
            print("👋 系统安全退出。")
            sys.exit(0)
        
        else:
            print("❌ 无效选择，请重试")
            time.sleep(1)

if __name__ == "__main__":
    main()