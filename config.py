"""模型配置和LLM初始化"""
import os
import httpx
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()


def get_llm(provider: str = "claude", temperature: float = 0.1) -> ChatOpenAI:
    """获取指定供应商的LLM实例，统一使用OpenAI兼容格式"""
    providers = {
        "claude": {
            "api_key": os.getenv("CLAUDE_API_KEY", ""),
            "base_url": os.getenv("CLAUDE_BASE_URL", ""),
            "model": os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
        },
        "qwen": {
            "api_key": os.getenv("QWEN_API_KEY", ""),
            "base_url": os.getenv("QWEN_BASE_URL", ""),
            "model": os.getenv("QWEN_MODEL", "qwen-plus"),
        },
        "glm": {
            "api_key": os.getenv("GLM_API_KEY", ""),
            "base_url": os.getenv("GLM_BASE_URL", ""),
            "model": os.getenv("GLM_MODEL", "glm-4"),
        },
    }

    cfg = providers[provider]

    # 构建 httpx client，显式禁用系统代理，处理SSL问题
    os.environ.pop("HTTP_PROXY", None)
    os.environ.pop("HTTPS_PROXY", None)
    os.environ.pop("http_proxy", None)
    os.environ.pop("https_proxy", None)

    http_client = httpx.Client(
        verify=False,  # 跳过SSL验证
        timeout=httpx.Timeout(120.0, connect=30.0),
    )

    return ChatOpenAI(
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        model=cfg["model"],
        temperature=temperature,
        http_client=http_client,
        max_retries=3,
    )


# ── 各节点默认使用的模型（可选: "claude", "qwen", "glm"，注意小写）──
CHUNKING_PROVIDER = "glm"
OPEN_CODING_PROVIDER = "glm"
MERGE_PROVIDER = "glm"
AXIAL_CODING_PROVIDER = "glm"

# ── 编码参数 ──────────────────────────────────────────
# 每轮处理多少个chunk
BATCH_SIZE = 5

# 连续多少轮无新概念时提示；不作为终止条件，也不能证明理论饱和
SATURATION_ROUNDS = 2

# ── 目录路径 ──────────────────────────────────────────
# 待处理的原始访谈文件目录
RAW_DATA_DIR = Path("raw_data")

# 已处理文件的归档目录
PROCESSED_DIR = Path("processed")

# 累积知识库目录
DB_DIR = Path("db")

# 报表输出目录
OUTPUT_DIR = Path("output")

# 知识库主文件路径
DB_FILE = DB_DIR / "coding_db.json"

# chunks 详情目录
CHUNKS_DIR = DB_DIR / "chunks"
