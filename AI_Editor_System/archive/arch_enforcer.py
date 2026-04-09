# file: tools/scaffold_generator.py
import os
import textwrap

class ArchitectureScaffolder:
    def __init__(self, root_dir="ai_system"):
        self.root = root_dir
        self.dirs = ["src/shared", "src/core"]

    def create_structure(self):
        for d in self.dirs:
            path = os.path.join(self.root, d)
            os.makedirs(path, exist_ok=True)
            with open(os.path.join(path, "__init__.py"), "w") as f:
                f.write("")
        print(f" Architecture scaffold created at {self.root}")

    def generate_contract_code(self):
        code = textwrap.dedent("""
            from pydantic import BaseModel, Field
            from enum import Enum
            from typing import Optional

            # --- 定义数据契约 ---
            # 这是UI和Core唯一的沟通语言。
            # 引用: 

            class OperationType(str, Enum):
                SUMMARIZE = "summarize"
                TRANSLATE = "translate"

            class AIRequest(BaseModel):
                text: str = Field(..., min_length=10, description="输入文本")
                operation: OperationType
                parameters: dict = Field(default_factory=dict)
                
                class Config:
                    frozen = True  # 强制不可变性，防止状态篡改

            class AIResponse(BaseModel):
                result_text: str
                meta_data: dict
                success: bool
        """)
        self._write_file("src/shared/contracts.py", code)

    def generate_core_template(self):
        code = textwrap.dedent("""
            from src.shared.contracts import AIRequest, AIResponse

            class AICoreProcessor:
                # 纯逻辑类，无状态，无UI依赖
                
                def process(self, request: AIRequest) -> AIResponse:
                    # 这里是业务逻辑的隔离区
                    # 不涉及任何全局状态变更
                    processed_text = f"Processed [{request.operation}]: {request.text[:20]}..."
                    return AIResponse(
                        result_text=processed_text,
                        meta_data={"processor": "v1.0"},
                        success=True
                    )
        """)
        self._write_file("src/core/processor.py", code)

    def _write_file(self, rel_path, content):
        path = os.path.join(self.root, rel_path)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content.strip())
        print(f"[Generated] {path}")

if __name__ == "__main__":
    scaffolder = ArchitectureScaffolder()
    scaffolder.create_structure()
    scaffolder.generate_contract_code()
    scaffolder.generate_core_template()