"""
JWT 鉴权
-------
网站版真实登录使用 Bearer Token：
前端把 token 保存在 localStorage，后续请求通过 Authorization 头携带。
（FastAPI 版：auth.py 不再依赖 Flask request/session。）
"""
import datetime

import jwt

from agent import config

ALGORITHM = "HS256"


def create_access_token(username: str) -> str:
    """生成带过期时间的访问令牌。"""
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + datetime.timedelta(hours=config.JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, config.JWT_SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str):
    """解析访问令牌，失败时返回 None。"""
    try:
        return jwt.decode(token, config.JWT_SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        return None


def get_current_username(auth_header: str = "") -> str | None:
    """从 Authorization 头解析 Bearer JWT，返回用户名；无有效令牌返回 None。"""
    if auth_header and auth_header.startswith("Bearer "):
        payload = decode_access_token(auth_header[7:])
        if payload:
            return payload.get("sub")
    return None
