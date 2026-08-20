
"""
用户记忆存储
------------
优先使用 PostgreSQL 保存真实网站登录数据；未配置数据库时退回本地 JSON，
便于本地演示和单机开发。
"""
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config
from . import database

HISTORY_LIMIT_PER_VILLAGE = 24
RECENT_QUESTION_LIMIT = 12

MODE_SUGGESTIONS = {
    "student": [
        "给我讲一个这里的小故事吧",
        "红军为什么要从这里走？",
        "这里最勇敢的人是谁？",
    ],
    "tourist": [
        "这里有哪些景点和美食？",
        "帮我规划一条2天路线",
        "从这里去下一个红色景点怎么走？",
    ],
    "researcher": [
        "不同档案对这个事件的记载有什么差异？",
        "这个事件在原始档案里的出处和页码是什么？",
        "这里还有哪些值得研究的档案版本？",
    ],
}


class UserMemoryStore:
    """用户、画像与长期记忆存储。"""

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir is None:
            base_dir = config.USER_MEMORY_DIR

        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.use_db = bool(config.DATABASE_URL)
        if self.use_db:
            database.init_db()
        else:
            self.path = self.base_dir / "users.json"
            self.data = self._load_json()

    # ---------- JSON fallback ----------
    def _load_json(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"users": {}}
        with self.path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _save_json(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    @staticmethod
    def _hash_password(password: str, salt: Optional[str] = None):
        salt = salt or secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            100000,
        ).hex()
        return salt, digest

    # ---------- 注册 / 登录 ----------
    def register(self, username: str, password: str):
        username = (username or "").strip()
        if not username:
            return False, "用户名不能为空"
        if not password:
            return False, "密码不能为空"
        if len(password) < 6:
            return False, "密码至少需要6位"
        if not any(ch.isalpha() for ch in password) or not any(ch.isdigit() for ch in password):
            return False, "密码必须同时包含字母和数字"

        if self.use_db:
            session = database.get_session()
            try:
                exists = (
                    session.query(database.User)
                    .filter_by(username=username)
                    .first()
                )
                if exists:
                    return False, "用户名已存在"

                salt, digest = self._hash_password(password)
                user = database.User(
                    username=username,
                    password_salt=salt,
                    password_hash=digest,
                )
                session.add(user)
                session.flush()
                session.add(database.UserProfile(user_id=user.id))
                session.commit()
                return True, username
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        if username in self.data["users"]:
            return False, "用户名已存在"

        salt, digest = self._hash_password(password)
        self.data["users"][username] = {
            "password_salt": salt,
            "password_hash": digest,
            "profile": {
                "persona_mode": "tourist",
                "village_counts": {},
                "recent_questions": [],
                "last_village": None,
            },
            "conversations": {},
        }
        self._save_json()
        return True, username

    def authenticate(self, username: str, password: str) -> Optional[str]:
        username = (username or "").strip()

        if self.use_db:
            session = database.get_session()
            try:
                user = (
                    session.query(database.User)
                    .filter_by(username=username)
                    .first()
                )
                if not user:
                    return None
                _, expected = self._hash_password(password, user.password_salt)
                return username if expected == user.password_hash else None
            finally:
                session.close()

        user = self.data["users"].get(username)
        if not user:
            return None
        _, expected = self._hash_password(password, user.get("password_salt", ""))
        return username if expected == user.get("password_hash", "") else None

    # ---------- 对话记忆 ----------
    def get_history(self, username: str, village: str) -> List[Dict[str, str]]:
        username = (username or "").strip()
        if not username or not village:
            return []

        if self.use_db:
            session = database.get_session()
            try:
                user = (
                    session.query(database.User)
                    .filter_by(username=username)
                    .first()
                )
                if not user:
                    return []
                rows = (
                    session.query(database.Conversation)
                    .filter_by(user_id=user.id, village=village)
                    .order_by(database.Conversation.created_at.desc())
                    .limit(HISTORY_LIMIT_PER_VILLAGE)
                    .all()
                )
                rows.reverse()
                return [{"role": r.role, "content": r.content} for r in rows]
            finally:
                session.close()

        user = self.data["users"].get(username)
        if not user:
            return []
        return list(user.get("conversations", {}).get(village, []))

    def append_turn(self, username: str, village: str, role: str, content: str) -> None:
        username = (username or "").strip()
        if not username or not village:
            return

        if self.use_db:
            session = database.get_session()
            try:
                user = (
                    session.query(database.User)
                    .filter_by(username=username)
                    .first()
                )
                if not user:
                    return
                session.add(
                    database.Conversation(
                        user_id=user.id,
                        village=village,
                        role=role,
                        content=content,
                    )
                )
                session.flush()

                excess = (
                    session.query(database.Conversation)
                    .filter_by(user_id=user.id, village=village)
                    .order_by(database.Conversation.created_at.desc())
                    .offset(HISTORY_LIMIT_PER_VILLAGE)
                    .all()
                )
                for item in excess:
                    session.delete(item)
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
            return

        user = self.data["users"].get(username)
        if not user:
            return
        conversations = user.setdefault("conversations", {})
        turns = conversations.setdefault(village, [])
        turns.append({"role": role, "content": content, "ts": time.time()})
        conversations[village] = turns[-HISTORY_LIMIT_PER_VILLAGE:]
        self._save_json()

    def clear_history(self, username: str, village: str) -> None:
        """删除某个用户与某个村寨的全部历史对话。"""
        username = (username or "").strip()
        if not username or not village:
            return

        if self.use_db:
            session = database.get_session()
            try:
                user = (
                    session.query(database.User)
                    .filter_by(username=username)
                    .first()
                )
                if not user:
                    return
                session.query(database.Conversation).filter_by(
                    user_id=user.id,
                    village=village,
                ).delete()
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
            return

        user = self.data["users"].get(username)
        if not user:
            return
        user.setdefault("conversations", {}).pop(village, None)
        self._save_json()

    # ---------- 用户画像 ----------
    def update_profile(
        self,
        username: str,
        persona_mode: Optional[str] = None,
        village: Optional[str] = None,
        question: Optional[str] = None,
    ) -> None:
        username = (username or "").strip()
        if not username:
            return

        if self.use_db:
            session = database.get_session()
            try:
                user = (
                    session.query(database.User)
                    .filter_by(username=username)
                    .first()
                )
                if not user:
                    return
                profile = user.profile
                if profile is None:
                    profile = database.UserProfile(user_id=user.id)
                    session.add(profile)
                    session.flush()

                if persona_mode in ("student", "tourist", "researcher"):
                    profile.persona_mode = persona_mode
                if village:
                    counts = dict(profile.village_counts or {})
                    counts[village] = counts.get(village, 0) + 1
                    profile.village_counts = counts
                    profile.last_village = village
                if question:
                    recent = list(profile.recent_questions or [])
                    recent.append(question)
                    profile.recent_questions = recent[-RECENT_QUESTION_LIMIT:]
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
            return

        user = self.data["users"].get(username)
        if not user:
            return
        profile = user.setdefault("profile", {})
        if persona_mode in ("student", "tourist", "researcher"):
            profile["persona_mode"] = persona_mode
        if village:
            counts = profile.setdefault("village_counts", {})
            counts[village] = counts.get(village, 0) + 1
            profile["last_village"] = village
        if question:
            recent = profile.setdefault("recent_questions", [])
            recent.append(question)
            profile["recent_questions"] = recent[-RECENT_QUESTION_LIMIT:]
        self._save_json()

    def get_profile(self, username: str) -> Dict[str, Any]:
        username = (username or "").strip()
        default = {
            "username": username,
            "persona_mode": "tourist",
            "preferred_villages": [],
            "recent_questions": [],
            "suggested_questions": MODE_SUGGESTIONS["tourist"],
            "village_counts": {},
        }
        if not username:
            return default

        if self.use_db:
            session = database.get_session()
            try:
                user = (
                    session.query(database.User)
                    .filter_by(username=username)
                    .first()
                )
                if not user:
                    return default
                profile = user.profile
                if profile is None:
                    return default

                persona_mode = profile.persona_mode or "tourist"
                counts = dict(profile.village_counts or {})
                recent = list(profile.recent_questions or [])
                preferred = sorted(counts, key=lambda name: (-counts[name], name))
                return {
                    "username": username,
                    "persona_mode": persona_mode,
                    "preferred_villages": preferred[:3],
                    "recent_questions": recent[-5:],
                    "suggested_questions": MODE_SUGGESTIONS.get(
                        persona_mode, MODE_SUGGESTIONS["tourist"]
                    ),
                    "village_counts": counts,
                }
            finally:
                session.close()

        user = self.data["users"].get(username)
        if not user:
            return default

        profile = user.get("profile", {})
        persona_mode = profile.get("persona_mode", "tourist")
        counts = profile.get("village_counts", {})
        preferred = sorted(counts, key=lambda name: (-counts[name], name))
        recent = profile.get("recent_questions", [])
        return {
            "username": username,
            "persona_mode": persona_mode,
            "preferred_villages": preferred[:3],
            "recent_questions": recent[-5:],
            "suggested_questions": MODE_SUGGESTIONS.get(persona_mode, MODE_SUGGESTIONS["tourist"]),
            "village_counts": counts,
        }
