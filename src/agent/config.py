"""
配置中心
------
统一配置来源：
- 环境变量 / .env：DEEPSEEK_API_KEY、DEEPSEEK_MODEL_NAME、WEB_PORT 等
- 代码内默认值：仅用于本地开发

模型选择：
- deepseek-v4-flash : DeepSeek V4 Flash，默认用于本项目
- deepseek-v4-pro   : DeepSeek V4 Pro，复杂任务备用
- deepseek-chat     : 兼容旧模型名
"""
import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _PROJECT_ROOT / ".env"

try:
    from dotenv import load_dotenv

    if _ENV_FILE.exists():
        load_dotenv(_ENV_FILE, encoding="utf-8-sig")
except Exception:
    pass

# ===================== LLM 配置 =====================
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

# 默认使用 DeepSeek V4 Flash
MODEL_NAME = os.environ.get("DEEPSEEK_MODEL_NAME", "deepseek-v4-flash")

BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

TEMPERATURE = 0.7
MAX_TOKENS = 4096

# ===================== 数据路径 =====================
PROJECT_DIR = os.environ.get("RED_ARCHIVE_PROJECT_DIR", str(_PROJECT_ROOT))
INDEX_DIR = os.path.join(PROJECT_DIR, "data", "index")

# 原始 OCR PDF 目录，用于证据链中的原 PDF 页面溯源
PDF_DIR = os.environ.get("RED_ARCHIVE_PDF_DIR", "")

# ===================== 检索参数 =====================
TOP_K = 4
MIN_SCORE = 0.0

# ===================== Web 服务配置 =====================
WEB_HOST = os.environ.get("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("WEB_PORT", "5000"))
WEB_DEBUG = os.environ.get("WEB_DEBUG", "0") == "1"

# ===================== 用户记忆与登录 =====================
SECRET_KEY = os.environ.get("RED_ARCHIVE_SECRET_KEY", "red-archives-agent-local-secret")
USER_MEMORY_DIR = os.path.join(PROJECT_DIR, "data", "user_memory")

# PostgreSQL 数据库：未配置时保持本地 JSON fallback
DATABASE_URL = os.environ.get("RED_ARCHIVE_DATABASE_URL", "")

# JWT 网站登录
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", SECRET_KEY)
JWT_EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "168"))

# ===================== 村寨列表 =====================
VILLAGES = [
    "皎平渡", "石鼓", "扎西", "寻甸", "柯渡", "楚雄",
    "昭通", "曲靖", "丽江", "宣威", "威信", "禄劝"
]
