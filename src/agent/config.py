"""
配置中心
------
集中管理所有可调参数，方便后续维护。

使用方式：
    1. 在系统环境变量中设置 DEEPSEEK_API_KEY（推荐，不要硬编码在代码里）
    2. 或者直接修改下面的 DEFAULT_API_KEY（不推荐，容易泄露）

模型选择：
    - deepseek-chat     : DeepSeek-V3，对话模型，快且便宜，适合 RAG 问答
    - deepseek-reasoner : DeepSeek-R1，推理模型，慢且贵，适合复杂推理
"""
import os
from pathlib import Path

# ??????????? .env ??????????? GitHub?
try:
    from dotenv import load_dotenv

    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    _ENV_FILE = _PROJECT_ROOT / ".env"
    if _ENV_FILE.exists():
        load_dotenv(_ENV_FILE, encoding="utf-8-sig")
except Exception:
    # ??? python-dotenv ? .env ???????????????
    pass

# ===================== LLM 配置 =====================
# API Key：优先读环境变量，其次用下方默认值
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "sk-你的key")

# 模型名称（推荐 deepseek-chat）
MODEL_NAME = "deepseek-chat"

# DeepSeek API 地址（OpenAI 兼容接口，无需修改）
BASE_URL = "https://api.deepseek.com"

# 生成参数
TEMPERATURE = 0.7        # 温度：越高越有创造性，越低越保守（0-1）
MAX_TOKENS = 1000        # 单次回复最大 token 数

# ===================== 数据路径 =====================
# 项目根目录：优先读 RED_ARCHIVE_PROJECT_DIR 环境变量（.env.example 中有说明），
# 否则按仓库实际位置推导（src/agent/config.py -> src/agent -> src -> 项目根）。
PROJECT_DIR = os.environ.get(
    "RED_ARCHIVE_PROJECT_DIR",
    str(Path(__file__).resolve().parents[2]),
)
INDEX_DIR = os.path.join(PROJECT_DIR, "data", "index")

# ===================== 检索参数 =====================
TOP_K = 4                # 每次检索返回的最相关文本块数量
MIN_SCORE = 0.0         # 最低匹配分数（低于此分数的结果丢弃）

# ===================== 村寨列表 =====================
# 系统支持的村寨（与索引中的地点关键词对应）
VILLAGES = [
    "皎平渡", "石鼓", "扎西", "寻甸", "柯渡", "楚雄",
    "昭通", "曲靖", "丽江", "宣威", "威信", "禄劝"
]
