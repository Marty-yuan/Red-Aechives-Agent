
"""
PostgreSQL 数据库层
------------------
网站版真实登录使用 PostgreSQL 保存：
- 用户
- 用户画像（讲解人格 / 访问村寨 / 最近问题）
- 按用户 + 村寨保存的长期对话记忆
"""
import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, scoped_session, sessionmaker

from . import config

Base = declarative_base()
_engine = None
SessionLocal = None


def init_db():
    """初始化数据库连接并自动建表。"""
    global _engine, SessionLocal

    if not config.DATABASE_URL:
        return None

    if _engine is not None:
        return _engine

    _engine = create_engine(
        config.DATABASE_URL,
        pool_pre_ping=True,
        future=True,
    )
    SessionLocal = scoped_session(
        sessionmaker(
            bind=_engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
    )
    Base.metadata.create_all(_engine)
    return _engine


def get_session():
    """返回一个数据库会话。"""
    if SessionLocal is None:
        init_db()
    if SessionLocal is None:
        raise RuntimeError(
            "数据库未初始化，请先配置 RED_ARCHIVE_DATABASE_URL 并启动 PostgreSQL"
        )
    return SessionLocal()


def now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


class User(Base):
    """注册用户。"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_salt = Column(String(64), nullable=False)
    password_hash = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=now_utc, nullable=False)

    profile = relationship(
        "UserProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    conversations = relationship(
        "Conversation",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserProfile(Base):
    """用户画像与讲解人格偏好。"""

    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    persona_mode = Column(String(20), nullable=False, default="tourist")
    village_counts = Column(JSON, nullable=False, default=dict)
    recent_questions = Column(JSON, nullable=False, default=list)
    last_village = Column(String(64), nullable=True)

    user = relationship("User", back_populates="profile")


class Conversation(Base):
    """按用户和村寨保存的长期对话记忆。"""

    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_user_village", "user_id", "village"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    village = Column(String(64), nullable=False)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=now_utc, nullable=False)

    user = relationship("User", back_populates="conversations")
