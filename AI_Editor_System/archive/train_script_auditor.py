import os
import pandas as pd
import numpy as np
from sklearn.metrics import accuracy_score, precision_recall_fscore_support
from transformers import (
    BertTokenizer,
    AutoModelForSequenceClassification,
    TrainingArguments,
    Trainer
)
from torch.utils.data import Dataset

# ==========================================
# 1. 基础配置
# ==========================================
MODEL_NAME = "hfl/chinese-roberta-wwm-ext"
OUTPUT_DIR = "./models/roberta-script-auditor"

# 剧本专用评估标签
ID2LABEL = {0: "合格", 1: "人设崩塌", 2: "逻辑漏洞", 3: "台词书面化", 4: "视听缺失"}
LABEL2ID = {v: k for k, v in ID2LABEL.items()}

# ==========================================
# 2. 数据处理类
# ==========================================
class ScriptDataset(Dataset):
    def __init__(self, texts, labels, tokenizer, max_len=128):
        self.encodings = tokenizer(
            texts, 
            truncation=True, 
            padding=True, 
            max_length=max_len
        )
        self.labels = labels

    def __getitem__(self, idx):
        import torch
        item = {key: torch.tensor(val[idx]) for key, val in self.encodings.items()}
        item['labels'] = torch.tensor(self.labels[idx], dtype=torch.long)
        return item

    def __len__(self):
        return len(self.labels)

# ==========================================
# 3. 评估指标计算
# ==========================================
def compute_metrics(pred):
    labels = pred.label_ids
    preds = pred.predictions.argmax(-1)
    
    # 计算 Macro-F1 和 准确率
    precision, recall, f1, _ = precision_recall_fscore_support(labels, preds, average='macro', zero_division=0)
    acc = accuracy_score(labels, preds)
    return {'accuracy': acc, 'f1': f1}

# ==========================================
# 4. 训练主流程
# ==========================================
def train():
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"🚀 训练设备: {device}")
    
    tokenizer = BertTokenizer.from_pretrained(MODEL_NAME)
    
    # ----------------------------------------------------
    # 加载真实数据 (由 generate_training_data.py 生成的 CSV)
    # ----------------------------------------------------
    CSV_PATH = r"D:\Claudedaoy\编辑系统\train_data.csv"
    if not os.path.exists(CSV_PATH):
        raise FileNotFoundError(f"❌ 未找到训练数据: {CSV_PATH}\n请先运行 generate_training_data.py 生成数据！")
    
    df = pd.read_csv(CSV_PATH)
    
    # 划分训练集 (80%) 和 测试集 (20%)
    train_df = df.sample(frac=0.8, random_state=42)
    eval_df = df.drop(train_df.index)
    
    print(f"📊 成功加载数据！训练集样本数: {len(train_df)}, 测试集样本数: {len(eval_df)}")

    # 实例化 Dataset
    dataset_train = ScriptDataset(train_df['text'].tolist(), train_df['label'].tolist(), tokenizer)
    dataset_eval = ScriptDataset(eval_df['text'].tolist(), eval_df['label'].tolist(), tokenizer)

    # ----------------------------------------------------
    # 加载预训练模型
    # ----------------------------------------------------
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_NAME, 
        num_labels=len(ID2LABEL), 
        id2label=ID2LABEL, 
        label2id=LABEL2ID
    ).to(device)

    # ----------------------------------------------------
    # 配置训练参数
    # ----------------------------------------------------
    args = TrainingArguments(
        output_dir=OUTPUT_DIR,
        num_train_epochs=3,                # 训练轮数
        per_device_train_batch_size=8,     # 批次大小 (如果显存溢出可改为 4)
        per_device_eval_batch_size=8,
        eval_strategy="epoch",             # 每个 epoch 评估一次 (兼容最新版 transformers)
        save_strategy="epoch",             # 每个 epoch 保存一次
        load_best_model_at_end=True,       # 训练结束加载最好的一版模型
        metric_for_best_model="f1",        # 以 F1 分数为最优标准
        logging_steps=5,
        report_to="none"                   # 关闭 wandb
    )

    trainer = Trainer(
        model=model, 
        args=args, 
        train_dataset=dataset_train, 
        eval_dataset=dataset_eval,
        compute_metrics=compute_metrics
    )

    # ----------------------------------------------------
    # 开始训练与保存
    # ----------------------------------------------------
    print("🎬 正在微调影视剧本专用哨兵模型...")
    trainer.train()
    
    # 保存最终模型到指定目录
    trainer.save_model(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)
    print(f"✅ 模型训练完成！已成功保存至：{OUTPUT_DIR}")

if __name__ == "__main__":
    train()