import os
import sys
import time
import statistics
import traceback
import glob
from typing import Dict, List, Any, Union

# ==========================================================
# 1. 环境配置
# ==========================================================
def configure_project_path():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    return current_dir

PROJECT_ROOT = configure_project_path()

# ==========================================================
# 2. 智能配置获取器 (自动探测 DB 路径)
# ==========================================================
def get_chroma_config() -> dict:
    config = {'db_path': None, 'collection_name': None}
    
    # 1. 尝试从项目设置读取
    try:
        from ingest_engine.config.settings import settings
        if hasattr(settings, 'chroma_db_path'):
            config['db_path'] = settings.chroma_db_path
        if hasattr(settings, 'chroma_collection_name'):
            config['collection_name'] = settings.chroma_collection_name
    except ImportError: pass

    # 2. 如果未找到配置，尝试智能扫描项目目录下的数据库文件夹
    if not config['db_path'] or not os.path.exists(config['db_path']):
        # 查找类似 ai_editor_chroma_db_v* 的文件夹
        potential_dbs = glob.glob(os.path.join(PROJECT_ROOT, "ai_editor_chroma_db_*"))
        if potential_dbs:
            # 按修改时间排序，取最新的一个
            newest_db = max(potential_dbs, key=os.path.getmtime)
            print(f"🔍 自动探测到最新数据库: {os.path.basename(newest_db)}")
            config['db_path'] = newest_db
        else:
            # 默认 fallback
            config['db_path'] = os.getenv('CHROMA_DB_PATH') or os.path.join(PROJECT_ROOT, "ai_editor_chroma_db_v9")
    
    os.environ['CHROMA_DB_PATH'] = config['db_path']
    return config

CONFIG = get_chroma_config()

try:
    from ingest_engine.components.chroma_adapter import ChromaRepository
except ImportError as e:
    print(f"❌ 环境错误: {e}")
    sys.exit(1)

# ==========================================================
# 3. 强健的诊断工具类
# ==========================================================
class DatabaseDoctor:
    def __init__(self):
        print("🏥 正在初始化诊断程序...")
        print(f"   📂 数据库路径: {CONFIG['db_path']}")
        
        try:
            self.repo = ChromaRepository()
            self.client = None
            self.collections = {}
            self.embed_fn = None
            
            # 1. 加载模型 (用于手动计算向量)
            if hasattr(self.repo, 'load_model'):
                print("   🔌 正在加载 Embedding 模型 (1024维)...")
                try:
                    self.repo.load_model()
                    print("   ✅ 模型加载完成")
                except Exception as model_e:
                    print(f"   ⚠️ 模型加载失败: {model_e}")

            # 2. 提取并封装模型函数
            raw_fn = getattr(self.repo, 'embedding_function', None)
            if not raw_fn: raw_fn = getattr(self.repo, 'embed_model', None)
            
            if raw_fn:
                print("   🔧 准备向量计算引擎...")
                
                class ManualEmbedder:
                    def __init__(self, model):
                        self.model = model
                    
                    def __call__(self, input: Union[str, List[str]]) -> List[List[float]]:
                        if isinstance(input, str): input = [input]
                        elif not isinstance(input, list): input = [str(input)]
                        try:
                            if hasattr(self.model, 'encode'):
                                vectors = self.model.encode(input, normalize_embeddings=True)
                            else:
                                vectors = self.model(input)
                            
                            if hasattr(vectors, 'tolist'): return vectors.tolist()
                            return vectors
                        except Exception as e:
                            print(f"      [Embedding Error] {e}")
                            return []

                self.embed_fn = ManualEmbedder(raw_fn)
            else:
                print("   ⚠️ 警告: 未找到 Embedding 模型，无法进行语义检索测试")
            
            # 3. 获取 Client
            if hasattr(self.repo, 'client'):
                self.client = self.repo.client
                if self.client is None and hasattr(self.repo, '_init_client'):
                    self.repo._init_client()
                    self.client = self.repo.client
            
            if not self.client:
                 raise ValueError("无法初始化 Chroma Client")
            
            # 4. 扫描集合
            self._scan_all_collections()
            
        except Exception as e:
            print(f"❌ 初始化失败: {e}")
            traceback.print_exc()
            sys.exit(1)
    
    def _scan_all_collections(self):
        try:
            available_collections = self.client.list_collections()
            if not available_collections:
                print("   ⚠️  数据库为空！")
                return
            
            print(f"   ℹ️  发现 {len(available_collections)} 个集合:")
            for coll in available_collections:
                # 🔥 [关键修改] 获取集合时不再传入 embedding_function
                # 避免触发 "Embedding function conflict" 错误
                # 我们稍后在查询时手动传入向量
                try:
                    collection_obj = self.client.get_collection(name=coll.name)
                    self.collections[coll.name] = collection_obj
                    print(f"      - {coll.name} (已连接)")
                except Exception as e:
                    print(f"      ❌ 连接 {coll.name} 失败: {e}")
            
        except Exception as e:
            print(f"   ❌ 扫描失败: {e}")

    def run_full_diagnosis(self):
        print("\n" + "="*50)
        print("🚀 数据量统计")
        print("="*50)

        total_count = 0
        for name, col in self.collections.items():
            c = col.count()
            print(f"   📦 {name}: {c} 条数据")
            total_count += c
            
        if total_count == 0:
            print("⚠️ 总数据量为 0，跳过后续测试。")
            return

        self.test_search_capability()

    def test_search_capability(self):
        print("\n" + "="*50)
        print("🧠 语义检索能力测试 (手动向量模式)")
        print("="*50)
        
        if not self.collections:
            print("   ❌ 无可用集合")
            return
            
        if not self.embed_fn:
            print("   ❌ 无 Embedding 模型，无法计算向量")
            return

        test_queries = ["蒙太奇手法", "电影剧本格式", "导演职责"]
        
        for query in test_queries:
            print(f"\n🔎 测试查询: '{query}'")
            
            # 1. 手动计算向量 (避开 Chroma 内部调用)
            try:
                query_vec = self.embed_fn(query)
                # print(f"   [DEBUG] 向量维度: {len(query_vec[0])}")
            except Exception as vec_e:
                print(f"   ❌ 向量计算失败: {vec_e}")
                continue

            found_any = False
            
            # 2. 遍历所有集合进行查询
            for coll_name, collection in self.collections.items():
                try:
                    if collection.count() == 0: continue

                    # 使用 query_embeddings 注入向量
                    results = collection.query(
                        query_embeddings=query_vec, 
                        n_results=1
                    )
                    
                    if not results['ids'] or len(results['ids'][0]) == 0:
                        continue
                    
                    # 解析
                    doc_text = results['documents'][0][0]
                    meta = results['metadatas'][0][0] or {}
                    distance = results.get('distances', [[]])[0][0]
                    
                    filename = os.path.basename(meta.get('source', '未知'))
                    
                    # 格式化输出 (符合用户期望的格式)
                    print(f"   ✅ [{coll_name}] 命中: {filename}")
                    print(f"      距离: {distance:.4f}")
                    # 移除换行符以便单行预览
                    preview = (doc_text[:60] + '...').replace('\n', ' ').replace('\r', ' ')
                    print(f"      预览: {preview}")
                    
                    found_any = True
                    
                except Exception as e:
                    print(f"   ❌ [{coll_name}] 检索出错: {e}")

            if not found_any:
                print("   ⚠️ 所有集合均未找到相关内容")

if __name__ == "__main__":
    doctor = DatabaseDoctor()
    doctor.run_full_diagnosis()