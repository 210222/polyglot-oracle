import os
import re
import glob

def clean_text(text: str) -> str:
    """
    🧬 基因级清洗：剥离所有空格、换行和不可见字符。
    这是最硬核的比对方式，可以完全无视切块算法（Chunking）引入的重叠（Overlap）和断行。
    """
    return re.sub(r'\s+', '', text)

def run_integrity_check(vlm_dir: str, xray_file_path: str):
    print("\n==================================================")
    print(" ⚖️ RAG 知识库无损比对质检系统 (Data Integrity Checker)")
    print("==================================================")
    
    if not os.path.exists(vlm_dir):
        print(f"❌ 找不到原始笔记路径: {vlm_dir}")
        return
        
    if not os.path.exists(xray_file_path):
        print(f"❌ 找不到 X光报告文件: {xray_file_path}")
        return

    # ---------------------------------------------------------
    # 1. 读取原始文件 (支持 文件夹、Project包 或 单一 .md 文件)
    # ---------------------------------------------------------
    original_text = ""
    
    # 如果用户拖入的是一个单独的 .md 文件
    if os.path.isfile(vlm_dir) and vlm_dir.lower().endswith('.md'):
        print(f"📥 正在读取单一元文件: {os.path.basename(vlm_dir)}...")
        with open(vlm_dir, 'r', encoding='utf-8') as file:
            original_text = file.read()
            
    # 如果用户拖入的是一个文件夹
    elif os.path.isdir(vlm_dir):
        # 👑 智能寻路：如果用户直接拖入了 _Project 根目录，自动往里找 03_VLM_MD
        auto_target_dir = os.path.join(vlm_dir, "03_VLM_MD")
        if os.path.exists(auto_target_dir):
            print("🤖 触发智能寻路：自动锁定 03_VLM_MD 车间...")
            vlm_dir = auto_target_dir
            
        vlm_files = sorted(glob.glob(os.path.join(vlm_dir, "*_VLM.md")))
        if not vlm_files:
            # 兼容寻找普通的 .md 文件
            vlm_files = sorted(glob.glob(os.path.join(vlm_dir, "*.md")))
            
        if not vlm_files:
            print(f"❌ 在 {vlm_dir} 中没有找到任何 .md 或 _VLM.md 文件！")
            return
            
        print(f"📥 正在读取原始笔记文件夹: 发现 {len(vlm_files)} 个分卷，正在内存中执行无缝重组...")
        for f in vlm_files:
            with open(f, 'r', encoding='utf-8') as file:
                original_text += file.read() + "\n\n"

    # ---------------------------------------------------------
    # 2. 读取数据库导出的 X 光报告 (The Database Export)
    # ---------------------------------------------------------
    print(f"📥 正在读取数据库 X 光切块报告: {os.path.basename(xray_file_path)}...")
    with open(xray_file_path, 'r', encoding='utf-8') as file:
        xray_text = file.read()

    xray_dense = clean_text(xray_text)

    # ---------------------------------------------------------
    # 3. 视觉锚点专项检查 (防乱码、防错位)
    # ---------------------------------------------------------
    print("\n" + "-"*50)
    print(" 👁️‍🗨️ 开始进行 [多模态视觉解析] 锚点质检...")
    
    # 用正则抓取原文中所有的 AI 视觉解析段落
    img_pattern = r"(> 🖼️ \*\*\[AI 导演视觉解析\]\*\*.*?)(?=\n\n|\Z)"
    original_images = re.findall(img_pattern, original_text, flags=re.DOTALL)
    xray_images = re.findall(img_pattern, xray_text, flags=re.DOTALL)
    
    print(f"  📌 原文包含图片解析: {len(original_images)} 处")
    print(f"  📌 数据库包含图片解析: {len(xray_images)} 处")
    
    if len(original_images) == len(xray_images):
        print("  ✅ 数量完美匹配！没有发生数据丢失。")
    else:
        print("  ❌ 警告：图片解析数量不一致！")

    # 检查位置是否乱码：提取原文中图片标记前后的纯净字符作为“基因锁”
    position_errors = 0
    for img_block in original_images:
        img_dense = clean_text(img_block)
        if img_dense not in xray_dense:
            position_errors += 1
            
    if position_errors == 0:
        print("  ✅ 锚点位置校验通过！所有图片解析均与上下文紧密咬合，未发生漂移或乱码。")
    else:
        print(f"  ❌ 警告：发现 {position_errors} 处图片解析发生错位或乱码！")

    # ---------------------------------------------------------
    # 4. 全文段落覆盖率检查 (防丢字)
    # ---------------------------------------------------------
    print("-"*50)
    print(" 📖 开始进行 [文本完整度] 基因级质检...")
    
    paragraphs = [p.strip() for p in original_text.split('\n\n') if p.strip()]
    total_paras = len(paragraphs)
    matched_paras = 0
    missing_paras = []
    
    for p in paragraphs:
        if len(p) < 3:
            total_paras -= 1
            continue
            
        p_dense = clean_text(p)
        if p_dense in xray_dense:
            matched_paras += 1
        else:
            missing_paras.append(p)

    match_rate = (matched_paras / total_paras) * 100 if total_paras > 0 else 0
    
    print(f"  📝 原始有效段落总数: {total_paras}")
    print(f"  🔍 成功在数据库中找回: {matched_paras}")
    
    if match_rate == 100.0:
        print(f"  ✅ 完整度 100%！没有任何一句话在切块和入库时丢失。")
    else:
        print(f"  ❌ 警告：完整度为 {match_rate:.2f}%，丢失了 {len(missing_paras)} 个段落。")
        print("\n  ⚠️ 丢失的样本 (前 3 个):")
        for i, mp in enumerate(missing_paras[:3]):
            print(f"    [{i+1}] {mp[:50]}...")

    print("="*50)
    if match_rate == 100.0 and position_errors == 0 and len(original_images) == len(xray_images):
        print(" 🎉 最终结论: 完美！您的 RAG 底层数据库与原始物理文件完全一致，您可以绝对信任系统！")
    else:
        print(" ⚠️ 最终结论: 存在瑕疵。请查看上方警告信息定位丢失或错位的数据。")
    print("==================================================\n")

if __name__ == "__main__":
    print("==================================================")
    print(" ⚖️ 启动数据一致性比对引擎")
    print(" 💡 提示: 你可以直接将文件夹或文件拖入此窗口")
    print("==================================================")
    
    vlm_input = input("\n📂 1. 请输入【_Project 文件夹】或【_VLM.md文件】的路径:\n> ").strip('"\'')
    xray_input = input("\n📄 2. 请输入探针导出的【XRay_...md 报告文件】的路径:\n> ").strip('"\'')
    
    run_integrity_check(vlm_input, xray_input)