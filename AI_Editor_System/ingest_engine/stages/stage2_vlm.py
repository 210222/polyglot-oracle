import os
import re
import base64
import logging
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", ".env"), override=True)

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("Stage2_VLM_Markdown")

_PROMPT = (
    "你是一个顶尖的电影导演和摄影指导。"
    "请用极其专业的影视视听语言（包含机位角度、景别、构图法则、光影分布、"
    "色彩冷暖、人物走位与情绪暗示等）详细解析这张图片。"
)


class VLMProcessor:
    def __init__(self):
        self.client = None
        self._init_api_client()

    def _init_api_client(self):
        from openai import OpenAI
        api_key = os.getenv("ZHIPU_API_KEY", "").strip()
        if not api_key:
            print("⚠️  未找到 ZHIPU_API_KEY，将使用 MOCK 模式")
            return
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://open.bigmodel.cn/api/paas/v4/"
        )
        print("✅ 智谱 GLM-4V Flash API 已就绪（云端视觉引擎）")

    def analyze_image(self, img_path: str) -> str:
        """调用智谱 GLM-4V Flash 对图片进行专业影视视听解析"""
        if self.client is None:
            return f"（MOCK）发现图片：{os.path.basename(img_path)}"
        try:
            ext = os.path.splitext(img_path)[1].lower()
            media_type = "image/png" if ext == ".png" else "image/jpeg"
            with open(img_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            response = self.client.chat.completions.create(
                model="glm-4v-flash",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url",
                         "image_url": {"url": f"data:{media_type};base64,{b64}"}},
                        {"type": "text", "text": _PROMPT},
                    ]
                }],
                max_tokens=512,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"GLM-4V 调用失败: {e}"

    def process_project_md(self, md_path):
        """
        🕵️ 扫描 Markdown 实体文件，寻找装甲标记并执行【灵魂替换】
        """
        md_dir = os.path.dirname(md_path)
        project_dir = os.path.dirname(md_dir) 
        
        vlm_md_dir = os.path.join(project_dir, "03_VLM_MD")
        os.makedirs(vlm_md_dir, exist_ok=True)
        
        md_name = os.path.basename(md_path)
        out_name = md_name.replace(".md", "_VLM.md")
        out_path = os.path.join(vlm_md_dir, out_name)
        
        print(f"\n📄 正在扫描实体笔记: {md_name}")
        with open(md_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        pattern = r"👉👉👉 \[AI_VISION_TARGET: (.*?)\] 👈👈👈"
        matches = list(re.finditer(pattern, content))
        
        new_content = content
        
        if not matches:
            print(f"⚠️ 报告：在这份文本中没有发现任何需要看图的装甲标记。已直接复制到输出目录。")
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            return out_path
            
        print(f"👁️‍🗨️ 雷达锁定！共发现 {len(matches)} 处视觉绝密档案，大模型开始执行解析...")

        for match in tqdm(matches, desc="VLM 视听降维打击中"):
            full_tag = match.group(0)
            img_path = match.group(1) 
            
            if not os.path.exists(img_path):
                desc_md = f"\n> ❌ **[图像丢失]**: 无法在物理硬盘中找到文件 {img_path}\n"
            else:
                ai_description = self.analyze_image(img_path)
                # 🛡️ 终极护盾注入：连 stage2 的产出也强制挂载绝对物理 ID!
                img_filename = os.path.basename(img_path)
                desc_md = f"\n> 🖼️ **[AI 导演视觉解析 | 绑定ID: {img_filename}]**: {ai_description}\n"
                
            new_content = new_content.replace(full_tag, desc_md)
            
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
            
        print("\n" + "="*50)
        print(f"🎉 灵魂注入完毕！")
        print(f"   📘 终极图文笔记已生成: {out_path}")
        print("="*50 + "\n")
        return out_path


def run(target_path: str = None):
    print("==================================================")
    print("🚀 全新 Stage 2: 实体化图文缝合与 VLM 看图引擎")
    print("==================================================")
    
    if not target_path:
        target_path = input("📂 请输入【Raw_MD 文件路径】或整个【Project 文件夹路径】: ").strip('"\'')
        
    vlm_processor = VLMProcessor()
        
    if os.path.isfile(target_path) and target_path.lower().endswith(".md"):
        vlm_processor.process_project_md(target_path)
        
    elif os.path.isdir(target_path):
        raw_md_dir = os.path.join(target_path, "02_Raw_MD")
        if not os.path.exists(raw_md_dir):
            raw_md_dir = target_path 
            
        md_files = [f for f in os.listdir(raw_md_dir) if f.lower().endswith('.md')]
        if not md_files:
            logger.warning("⚠️ 该路径下没有找到待处理的 .md 实体文件！")
            return
            
        print(f"📦 侦测到批处理任务，共 {len(md_files)} 份文本待唤醒...")
        for f in md_files:
            vlm_processor.process_project_md(os.path.join(raw_md_dir, f))
    else:
        logger.error("❌ 路径无效。")

if __name__ == "__main__":
    run()