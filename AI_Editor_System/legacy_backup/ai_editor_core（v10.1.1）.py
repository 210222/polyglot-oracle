# -*- coding: utf-8 -*-
"""
ai_editor_core.py - v10.2 Fused Edition (Intelligent Continuity)
Internal Codename: "The Blind Oracle"

Architecture:
    - Body (Infra): v10.1 Atomic I/O & Model Management
    - Brain (Logic): v10.2 Intelligent RAG Layer (Semantic Bucketing)
    - Soul (Prompt): Meta-Prompt v10.2 with Visual Ledger & Rule Enforcement
    - Target: Midjourney v6.1 & Runway Gen-3 Production Pipeline

Author: AI Architecture Team
Version: 10.2.0 Fused
"""

import os
import sys
import json
import time
import re
import logging
import uuid
import shutil
import random
from typing import List, Dict, Any, Optional, Tuple, Union
from contextlib import contextmanager

# --- 1. 基础设施依赖 (From v10.1) ---
import torch
from dotenv import load_dotenv

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()

# 常量路径配置
DB_PATH = os.path.join(os.path.dirname(__file__), "ai_memory_db")
LOCAL_MODEL_DIR = os.path.join(os.path.dirname(__file__), "local_models")

# --- 2. 遥测静音补丁 ---
try:
    import chromadb
    def mute_telemetry(*args, **kwargs): return None
    if hasattr(chromadb, 'telemetry'):
        import posthog
        posthog.capture = mute_telemetry
        posthog.disabled = True
except ImportError:
    pass

# --- 3. 核心 ML 依赖导入 ---
try:
    from FlagEmbedding import BGEM3FlagModel, FlagReranker
    from chromadb.config import Settings
    from huggingface_hub import snapshot_download
except ImportError:
    logger.critical("⚠️ 缺少必要依赖库 (FlagEmbedding, chromadb)。RAG 功能将受限。")

# ==============================================================================
# SECTION A: THE SOUL (v10.2 System Prompts & Presets)
# ==============================================================================

SYSTEM_PROMPT_V10_2 = """
ROLE DEFINITION:
You are the AI Visual Foundation Architect (v10.2 - Intelligent RAG Edition).
Internal Codename: "The Blind Oracle".

CORE DIRECTIVE: 
Translate [USER SCRIPT] into Production Prompts. You must maintain consistency by cross-referencing [VISUAL LEDGER] and strictly adhering to the structured [INTELLIGENT KNOWLEDGE LAYER].

1. INTELLIGENCE ANALYSIS KERNEL (Mandatory Deep CoT)
- Phase A: Constraint Check (Highest Priority). 
  Look at [WORLD_RULES] in the Knowledge Layer. If the script violates a rule (e.g., "Script says red sword, Rule says always blue"), you MUST CORRECT IT and note the correction in `state_update`.
- Phase B: Technical Enforcement.
  Apply specs from [TECH_SPECS] (e.g., specific camera lenses, render settings) to the `generative_cornerstones`.
- Phase C: State Delta Scan (The Skin).
  Check [VISUAL LEDGER]. Does the character's physical state change? (e.g., "clean" -> "muddy").
- Phase D: Anchor Check (The Face).
  If hero_ref_url exists, apply --cref {url}. 
  Weight Logic: No State Change -> --cw 100; State Change -> --cw 20.
- Phase E: Syntax Differentiation.
  T2I (Midjourney): Subject + Environment + Lighting + Style.
  I2V (Runway/Sora): Camera Movement + Subject Action + Atmospherics (NO static descriptions).

2. STYLE INJECTION LIBRARY (Reference Only, enforced by Python Logic):
[Style: MJ_REALISM_V10]: --v 6.1 --stylize 250 --style raw --ar 16:9
[Style: NIJI_VECTOR_POP]: --niji 6 --stylize 100 --ar 1:1

3. DATA INPUT STREAMS:

[VISUAL LEDGER] (Character State):
$$JSON_STATE_HERE$$

[INTELLIGENT KNOWLEDGE LAYER] (Structured Constraints):
$$SMART_RAG_CONTEXT$$

[USER SCRIPT] (Immediate Narrative):
$$User_Script_Here$$

4. OUTPUT SCHEMA (JSON ONLY):
{
  "assets": [
    {
      "scene_id": "SC_001",
      "narrative": {"cn": "Human readable summary...", "subtext": "Hidden emotion..."},
      "generative_cornerstones": {
        "t2i_prompt": "/imagine prompt: [Subject] [Environment] [Lighting] [Style] --cref [URL] --cw [W]",
        "i2v_prompt": "[Prefix] [Camera Action] [Subject Action] [Atmospherics]",
        "negative_prompt": "text, watermark, low quality, distortion"
      },
      "state_update": {
        "visual_tags_change": ["new_tag"] or null, 
        "reason": "Corrected 'Red Sword' to 'Blue Sword' based on WORLD_RULES."
      }
    }
  ]
}
"""

# [v10.1 Rich Presets] 保留丰富的预设库
VISUAL_PRESETS = {
    "MJ_REALISM_V10": {
        "name": "Extreme Realism v10",
        "engine": "midjourney",
        "mj_params": {"version": "--v 6.1", "stylize": 250, "style": "raw", "aspect_ratio": "--ar 16:9"},
        "description": "Commercial photography standard. High fidelity."
    },
    "MJ_SURREAL_DREAM": {
        "name": "Deep Surreal Dream",
        "engine": "midjourney",
        "mj_params": {"version": "--v 6.1", "stylize": 750, "weird": 500, "aspect_ratio": "--ar 3:2"},
        "description": "High abstraction for brainstorming."
    },
    "NIJI_VECTOR_POP": {
        "name": "Vector Pop",
        "engine": "niji",
        "mj_params": {"version": "--niji 6", "stylize": 100, "aspect_ratio": "--ar 1:1"},
        "description": "Clean lines, flat design, iconographic assets."
    },
    "VID_CINE_TRACK": {
        "name": "Cinematic Tracking",
        "engine": "runway_gen3",
        "rw_prefix": "Slow tracking shot:",
        "rw_motion_params": {"zoom": 1.0, "horizontal": 0},
        "description": "Stable subject tracking."
    },
    "VID_FPV_FAST": {
        "name": "Fast FPV Drone",
        "engine": "runway_gen3",
        "rw_prefix": "High speed FPV drone:",
        "rw_motion_params": {"zoom": 1.2, "horizontal": 2},
        "description": "High impact action sequences."
    }
}

# ==============================================================================
# SECTION B: THE BODY (Infrastructure - From v10.1)
# ==============================================================================

@contextmanager
def safe_open_w(path: str, mode: str = 'w', encoding: str = 'utf-8'):
    """Atomic Write Handler."""
    dir_name = os.path.dirname(path)
    if dir_name and not os.path.exists(dir_name): os.makedirs(dir_name, exist_ok=True)
    temp_path = f"{path}.tmp_{uuid.uuid4().hex}"
    try:
        with open(temp_path, mode, encoding=encoding) as f: yield f
    except Exception as e:
        if os.path.exists(temp_path): os.remove(temp_path)
        raise e
    else:
        try: os.replace(temp_path, path)
        except OSError:
            if os.path.exists(path): os.remove(path)
            os.rename(temp_path, path)

def download_model_static(repo_id: str, local_folder_name: str) -> str:
    """Forces model download to local directory."""
    target_dir = os.path.join(LOCAL_MODEL_DIR, local_folder_name)
    is_cached = False
    if os.path.exists(target_dir):
        if os.path.exists(os.path.join(target_dir, "config.json")) or \
           os.path.exists(os.path.join(target_dir, "model.safetensors")):
            is_cached = True
    
    if not is_cached:
        logger.info(f"📥 Downloading {repo_id}...")
        try:
            snapshot_download(repo_id=repo_id, local_dir=target_dir, local_dir_use_symlinks=False, resume_download=True)
        except Exception as e:
            logger.error(f"❌ Download failed: {e}")
            raise e
    return target_dir

class EngineResources:
    """Singleton Resource Manager (v10.1 Infra)."""
    embed_model = None
    reranker = None
    chroma_client = None
    kbs: Dict[str, Any] = {}
    is_ready = False
    
    @classmethod
    def init_engine(cls):
        if cls.is_ready: return
        logger.info(">>> Initializing AI Film Engine Pro v10.2 (Fused)...")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        
        try:
            # 1. Load Embedding Model
            bge_path = download_model_static('BAAI/bge-m3', 'bge-m3')
            cls.embed_model = BGEM3FlagModel(bge_path, use_fp16=True, device=device)
            
            # 2. Load Re-Ranker (Optional)
            try:
                reranker_path = download_model_static('BAAI/bge-reranker-base', 'bge-reranker-base')
                cls.reranker = FlagReranker(reranker_path, use_fp16=True)
            except:
                logger.warning("Re-Ranker unavailable, using dense retrieval only.")

            # 3. Connect to ChromaDB
            cls.chroma_client = chromadb.PersistentClient(path=DB_PATH, settings=Settings(anonymized_telemetry=False, allow_reset=False))
            
            # 4. Initialize Knowledge Bases
            cls.kbs = {
                "screenplay_expert": cls.chroma_client.get_or_create_collection("screenplay_expert"),
                "ue5_technical_specs": cls.chroma_client.get_or_create_collection("ue5_technical_specs"),
                "shared_common": cls.chroma_client.get_or_create_collection("shared_common"),
                "director_expert": cls.chroma_client.get_or_create_collection("director_expert")
            }
            cls.is_ready = True
            logger.info("✅ Engine Ready.")
        except Exception as e:
            logger.error(f"❌ Engine Init Failed: {e}")

# ==============================================================================
# SECTION C: INTELLIGENT RAG INTERFACE (The Brain - From v10.2)
# ==============================================================================

class IntelligentRAGLayer:
    """
    [v10.2 Core] Semantic Bucketing RAG Interface.
    Internal Codename: "The Prism"
    """

    @staticmethod
    def _query_collection(collection_name: str, query_vec: list, top_k: int = 3) -> List[Dict]:
        """Atomic safe query to ChromaDB."""
        try:
            if collection_name not in EngineResources.kbs: return []
            collection = EngineResources.kbs[collection_name]
            results = collection.query(query_embeddings=[query_vec], n_results=top_k, include=["documents", "metadatas", "distances"])
            
            flat_results = []
            if results['documents']:
                for i, doc in enumerate(results['documents'][0]):
                    meta = results['metadatas'][0][i]
                    flat_results.append({"content": doc, "metadata": meta})
            return flat_results
        except Exception as e:
            logger.warning(f"⚠️ Query Error ({collection_name}): {e}")
            return []

    @classmethod
    def synthesize_context(cls, query: str) -> str:
        """Core Interface: Transforms Query -> Structured Context."""
        if not EngineResources.is_ready or not EngineResources.embed_model:
            return "(Knowledge Engine Offline)"

        try:
            # 1. Encode
            query_vec = EngineResources.embed_model.encode([query], return_dense=True, return_sparse=False)['dense_vecs'][0].tolist()
            
            # 2. Fan-out Retrieval
            raw_docs = []
            for kb in ["screenplay_expert", "ue5_technical_specs", "shared_common", "director_expert"]:
                raw_docs.extend(cls._query_collection(kb, query_vec, top_k=2))

            # 3. Semantic Bucketing
            buckets = {"WORLD_RULES": [], "TECH_SPECS": [], "REFERENCES": []}
            
            for doc in raw_docs:
                meta = doc.get("metadata", {})
                content = doc.get("content", "").strip()
                is_vip = str(meta.get("is_vip", "False")).lower() == "true"
                kb_cat = meta.get("kb_category", "")

                if is_vip:
                    buckets["WORLD_RULES"].append(f"- [AXIOM] {content}")
                elif kb_cat in ["ue5_technical_specs", "director_expert"]:
                    buckets["TECH_SPECS"].append(f"- [RENDER_SPEC] {content}")
                else:
                    buckets["REFERENCES"].append(f"- {content}")

            # 4. Synthesize Blocks
            blocks = []
            if buckets["WORLD_RULES"]:
                blocks.append("\n<SECTION: WORLD_RULES (HIGHEST PRIORITY - OVERRIDE USER SCRIPT)>\n" + "\n".join(buckets["WORLD_RULES"]))
            if buckets["TECH_SPECS"]:
                blocks.append("\n<SECTION: TECH_SPECS (VISUAL GUIDANCE)>\n" + "\n".join(buckets["TECH_SPECS"]))
            if buckets["REFERENCES"]:
                blocks.append("\n<SECTION: REFERENCES (CONTEXT)>\n" + "\n".join(buckets["REFERENCES"]))
            
            return "\n".join(blocks) if blocks else "(No relevant knowledge found)"
            
        except Exception as e:
            logger.error(f"RAG Synthesis Error: {e}")
            return "(RAG Error)"

# ==============================================================================
# SECTION D: LOGIC HELPERS (From v10.1)
# ==============================================================================

def _sanitize_syntax(prompt: str) -> str:
    """Moves all '--' parameters to the end."""
    params = re.findall(r'(--[a-zA-Z]+(?:\s+[a-zA-Z0-9:.]+)?)\s*', prompt)
    clean_text = re.sub(r'(--[a-zA-Z]+(?:\s+[a-zA-Z0-9:.]+)?)\s*', '', prompt).strip()
    return f"{clean_text} {' '.join(list(dict.fromkeys(params)))}".strip()

def _sanitize_negative_prompts(prompt: str) -> str:
    """Converts negatives to positives for Video models."""
    replacements = {
        "no shaking": "steady tripod shot",
        "don't move": "static shot",
        "no blur": "deep depth of field, sharp focus"
    }
    lower = prompt.lower()
    for neg, pos in replacements.items():
        if neg in lower: lower = lower.replace(neg, pos)
    return lower

def _mock_llm_api_call(prompt: str, visual_ledger: Dict) -> str:
    """
    [v10.2 Mock System] Simulates Intelligent Decision Making.
    This logic detects conflicts between 'User Script' and 'World Rules'.
    """
    script_part = prompt.split("$$User_Script_Here$$")[-1].lower() if "$$User_Script_Here$$" in prompt else prompt.lower()
    
    # 1. Simulate RAG Conflict Logic (Phase A)
    correction = None
    t2i_desc = "Hero standing in scene"
    
    if "red sword" in script_part:
        correction = "Corrected 'Red Sword' to 'Azure Blade' based on WORLD_RULES."
        t2i_desc = "Hero holding a glowing Azure Blade, blue light reflecting on rain"
    elif "mud" in script_part:
        t2i_desc = "Hero covered in mud, clothes torn, gritty texture"
    
    # 2. Simulate Anchor Check (Phase D)
    cref_param = ""
    cw_val = 100
    if visual_ledger.get("hero_ref_url"):
        if "mud" in script_part or "torn" in script_part: cw_val = 20 # State change
        cref_param = f"--cref {visual_ledger['hero_ref_url']} --cw {cw_val}"

    # 3. Generate Output
    response = {
        "assets": [{
            "scene_id": "SC_GEN_001",
            "narrative": {"cn": "AI 生成的场景描述", "subtext": "潜在的情绪流露"},
            "generative_cornerstones": {
                "t2i_prompt": f"/imagine prompt: Cinematic shot, {t2i_desc}, dramatic lighting {cref_param}",
                "i2v_prompt": "Slow tracking shot. Rain falling. Hero breathing heavily.",
                "negative_prompt": "text, watermark, low quality"
            },
            "state_update": {"visual_tags_change": ["muddy"] if "mud" in script_part else [], "reason": correction}
        }]
    }
    
    thinking = f"""<thinking>
Phase A (Rules): Conflict detected? {'YES' if correction else 'NO'}.
Phase B (Specs): Applying volumetric fog.
Phase C (Ledger): Physical state update -> {'Muddy' if 'mud' in script_part else 'Stable'}.
Phase D (Anchor): Cref active. CW set to {cw_val}.
</thinking>"""
    
    return f"{thinking}\n```json\n{json.dumps(response)}\n```"

# ==============================================================================
# SECTION E: THE ORCHESTRATOR (v10.2 Fused)
# ==============================================================================

def get_ai_response(
    text_input: str, 
    context: bool = True, 
    style_preset: str = "MJ_REALISM_V10",
    visual_ledger: Dict = None
) -> Dict[str, Any]:
    """The Core Interface."""
    if not EngineResources.is_ready: EngineResources.init_engine()
    
    if visual_ledger is None:
        visual_ledger = {"hero_ref_url": None, "physical_state": "Initial"}

    # 1. Intelligent RAG Retrieval
    rag_context = "(No Context)"
    if context:
        logger.info(f"🧠 Invoking Intelligent RAG for: {text_input[:20]}...")
        rag_context = IntelligentRAGLayer.synthesize_context(text_input)

    # 2. Meta-Prompt Construction
    full_prompt = SYSTEM_PROMPT_V10_2.replace("$$JSON_STATE_HERE$$", json.dumps(visual_ledger))
    full_prompt = full_prompt.replace("$$SMART_RAG_CONTEXT$$", rag_context)
    full_prompt = full_prompt.replace("$$User_Script_Here$$", text_input)

    # 3. LLM Execution (Mock)
    raw_response = _mock_llm_api_call(full_prompt, visual_ledger)
    
    # 4. Parsing
    try:
        json_match = re.search(r"```json\n(.*?)\n```", raw_response, re.DOTALL)
        data = json.loads(json_match.group(1)) if json_match else json.loads(raw_response)
    except:
        return {"success": False, "error": "Parse Error", "raw": raw_response}

    # 5. Post-Processing (Syntax & Video Logic)
    preset = VISUAL_PRESETS.get(style_preset, VISUAL_PRESETS["MJ_REALISM_V10"])
    is_video = "VID" in style_preset
    
    for asset in data.get("assets", []):
        gc = asset.get("generative_cornerstones", {})
        
        # T2I Logic
        t2i = gc.get("t2i_prompt", "")
        if not is_video:
            mj_params = preset.get("mj_params", {})
            if "--v" not in t2i: t2i += f" {mj_params.get('version', '')}"
            if "--s" not in t2i: t2i += f" --s {mj_params.get('stylize', 250)}"
            if mj_params.get("style") == "raw" and "style raw" not in t2i: t2i += " --style raw"
            asset["generative_cornerstones"]["t2i_prompt"] = _sanitize_syntax(t2i)
            
        # I2V Logic
        i2v = gc.get("i2v_prompt", "")
        if is_video:
            prefix = preset.get("rw_prefix", "")
            if prefix and prefix.lower() not in i2v.lower(): i2v = f"{prefix} {i2v}"
            asset["generative_cornerstones"]["i2v_prompt"] = _sanitize_negative_prompts(i2v)

    return {
        "success": True, 
        "thinking": raw_response.split("```json")[0].strip(),
        "assets": data.get("assets", []),
        "new_ledger": visual_ledger # In real logic, update based on state_update
    }

def ai_editor_inference(text: str, task: str, user_id: str = "default"):
    """Legacy Wrapper for app.py compatibility."""
    mapping = {"合规审核": "MJ_REALISM_V10", "文风转换": "NIJI_VECTOR_POP"}
    res = get_ai_response(text, style_preset=mapping.get(task, "MJ_REALISM_V10"))
    output = f"### 🧠 AI 思考过程 (v10.2 CoT)\n{res.get('thinking', '')}\n\n"
    for a in res.get('assets', []):
        t2i = a['generative_cornerstones']['t2i_prompt']
        output += f"**SCENE**: {a.get('narrative', {}).get('cn')}\n- 🎨 Prompt: `{t2i}`\n"
    return output

if __name__ == "__main__":
    EngineResources.init_engine()
    print("🚀 Running v10.2 Fused Test: 'Red Sword' Conflict...")
    res = get_ai_response("Hero holds a red sword in the rain.", visual_ledger={"hero_ref_url": "[http://img.com/hero.jpg](http://img.com/hero.jpg)"})
    print(json.dumps(res, indent=2, ensure_ascii=False))