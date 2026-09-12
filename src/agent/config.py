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
        load_dotenv(_ENV_FILE, encoding="utf-8-sig", override=True)
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
# 1=优先混合检索（char TF-IDF + word TF-IDF/BGE + RRF），0=仅 char TF-IDF
USE_HYBRID_RETRIEVER = os.environ.get("RED_ARCHIVE_USE_HYBRID", "1") != "0"

# ===================== Web 服务配置 =====================
WEB_HOST = os.environ.get("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("WEB_PORT", "5000"))
WEB_DEBUG = os.environ.get("WEB_DEBUG", "0") == "1"

# ===================== 用户记忆与登录 =====================
# 安全说明：不再提供硬编码默认密钥。未配置环境变量时，启动时生成一次性随机密钥——
# 本地开发可正常登录使用，但服务重启后所有已签发 token 失效（需重新登录）。
# 生产/演示部署请务必通过 RED_ARCHIVE_SECRET_KEY（或 JWT_SECRET_KEY）配置固定密钥。
def _load_secret(env_name: str) -> str:
    value = os.environ.get(env_name, "").strip()
    if value:
        return value
    import secrets
    generated = secrets.token_urlsafe(32)
    print(f"[config] 警告：未设置 {env_name}，已生成一次性随机密钥；重启后所有登录态将失效。"
          f"生产环境请配置 {env_name} 环境变量。")
    return generated

SECRET_KEY = _load_secret("RED_ARCHIVE_SECRET_KEY")
USER_MEMORY_DIR = os.path.join(PROJECT_DIR, "data", "user_memory")

# PostgreSQL 数据库：未配置时保持本地 JSON fallback
DATABASE_URL = os.environ.get("RED_ARCHIVE_DATABASE_URL", "")

# JWT 网站登录
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "").strip() or SECRET_KEY
JWT_EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "168"))

# ===================== 天气服务（和风天气 QWeather，免费个人版） =====================
# 申请地址 https://dev.qweather.com/，免费订阅 1000 次/天；留空则客流热力不接天气
QWEATHER_API_KEY = os.environ.get("QWEATHER_API_KEY", "")
QWEATHER_BASE_URL = os.environ.get("QWEATHER_BASE_URL", "https://devapi.qweather.com")

# ===================== 村寨列表 =====================
VILLAGES = [
    "皎平渡", "石鼓", "扎西", "寻甸", "柯渡", "楚雄",
    "昭通", "曲靖", "丽江", "宣威", "威信", "禄劝"
]
