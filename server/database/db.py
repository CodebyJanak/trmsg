"""trmsg - Database Models"""
from datetime import datetime
from typing import Optional
import enum
from sqlalchemy import (Column, Integer, String, Boolean, DateTime,
    ForeignKey, Text, BigInteger, Enum, Index, JSON, Float)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, relationship
from server.config import settings

class Base(DeclarativeBase):
    pass

class FriendStatus(enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    BLOCKED = "blocked"

class MessageType(enum.Enum):
    TEXT = "text"
    FILE = "file"
    IMAGE = "image"
    SYSTEM = "system"
    POLL = "poll"
    BURN = "burn"
    VOICE = "voice"
    CODE = "code"
    ANNOUNCEMENT = "announcement"

class RoomType(enum.Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    DIRECT = "direct"
    ANNOUNCEMENT = "announcement"

class UserStatus(enum.Enum):
    ONLINE = "online"
    AWAY = "away"
    BUSY = "busy"
    INVISIBLE = "invisible"
    OFFLINE = "offline"

class UserRole(enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    VIP = "vip"
    MEMBER = "member"
    BOT = "bot"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    display_name = Column(String(100), nullable=True)
    avatar_color = Column(String(20), default="#00ff88")
    bio = Column(Text, nullable=True)
    status = Column(Enum(UserStatus), default=UserStatus.OFFLINE)
    status_message = Column(String(150), nullable=True)
    role = Column(Enum(UserRole), default=UserRole.MEMBER)
    theme = Column(String(20), default="cyberpunk")
    is_active = Column(Boolean, default=True)
    is_bot = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    last_seen = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    total_messages = Column(Integer, default=0)
    total_reactions = Column(Integer, default=0)
    total_files = Column(Integer, default=0)
    dnd_start = Column(String(10), nullable=True)
    dnd_end = Column(String(10), nullable=True)
    alert_keywords = Column(JSON, nullable=True)
    public_key = Column(Text, nullable=True)
    notification_sound = Column(Boolean, default=True)
    score = Column(Integer, default=0)

    sent_messages = relationship("Message", foreign_keys="Message.sender_id", back_populates="sender")
    room_memberships = relationship("RoomMember", back_populates="user")
    sent_requests = relationship("Friendship", foreign_keys="Friendship.requester_id", back_populates="requester")
    received_requests = relationship("Friendship", foreign_keys="Friendship.addressee_id", back_populates="addressee")
    reactions = relationship("Reaction", back_populates="user")
    poll_votes = relationship("PollVote", back_populates="user")
    game_stats = relationship("GameStat", back_populates="user")

class Room(Base):
    __tablename__ = "rooms"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True, nullable=False)
    display_name = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    topic = Column(String(200), nullable=True)
    category = Column(String(50), nullable=True)
    room_type = Column(Enum(RoomType), default=RoomType.PUBLIC)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    icon = Column(String(10), default="💬")
    banner_color = Column(String(20), default="#00ff88")
    password_hash = Column(String(255), nullable=True)
    is_read_only = Column(Boolean, default=False)
    slow_mode_seconds = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    total_messages = Column(Integer, default=0)
    tags = Column(JSON, nullable=True)
    pinned_message_id = Column(Integer, nullable=True)

    messages = relationship("Message", back_populates="room")
    members = relationship("RoomMember", back_populates="room")
    owner = relationship("User", foreign_keys=[owner_id])
    invite_links = relationship("InviteLink", back_populates="room")

class RoomMember(Base):
    __tablename__ = "room_members"
    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    joined_at = Column(DateTime, default=datetime.utcnow)
    is_admin = Column(Boolean, default=False)
    is_muted = Column(Boolean, default=False)
    nickname = Column(String(50), nullable=True)
    last_read_message_id = Column(Integer, nullable=True)
    notifications = Column(Boolean, default=True)
    room = relationship("Room", back_populates="members")
    user = relationship("User", back_populates="room_memberships")
    __table_args__ = (Index("idx_room_user", "room_id", "user_id", unique=True),)

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=True)
    message_type = Column(Enum(MessageType), default=MessageType.TEXT)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=True)
    is_encrypted = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    is_pinned = Column(Boolean, default=False)
    burn_at = Column(DateTime, nullable=True)
    reply_to_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    edited_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    metadata_ = Column("metadata", JSON, nullable=True)
    code_language = Column(String(30), nullable=True)

    sender = relationship("User", back_populates="sent_messages", foreign_keys=[sender_id])
    room = relationship("Room", back_populates="messages")
    file = relationship("FileUpload", back_populates="message")
    reply_to = relationship("Message", remote_side=[id], foreign_keys=[reply_to_id])
    reactions = relationship("Reaction", back_populates="message")
    __table_args__ = (Index("idx_room_created", "room_id", "created_at"),)

class Reaction(Base):
    __tablename__ = "reactions"
    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    emoji = Column(String(10), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    message = relationship("Message", back_populates="reactions")
    user = relationship("User", back_populates="reactions")
    __table_args__ = (Index("idx_reaction_msg_user_emoji", "message_id", "user_id", "emoji", unique=True),)

class Poll(Base):
    __tablename__ = "polls"
    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False)
    question = Column(String(500), nullable=False)
    options = Column(JSON, nullable=False)
    is_multiple = Column(Boolean, default=False)
    is_anonymous = Column(Boolean, default=True)
    ends_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    votes = relationship("PollVote", back_populates="poll")

class PollVote(Base):
    __tablename__ = "poll_votes"
    id = Column(Integer, primary_key=True, index=True)
    poll_id = Column(Integer, ForeignKey("polls.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    option_index = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    poll = relationship("Poll", back_populates="votes")
    user = relationship("User", back_populates="poll_votes")

class FileUpload(Base):
    __tablename__ = "files"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    mime_type = Column(String(100), nullable=True)
    storage_path = Column(String(500), nullable=False)
    uploader_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    download_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    message = relationship("Message", back_populates="file")
    uploader = relationship("User")

class Friendship(Base):
    __tablename__ = "friendships"
    id = Column(Integer, primary_key=True, index=True)
    requester_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    addressee_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(Enum(FriendStatus), default=FriendStatus.PENDING)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    requester = relationship("User", foreign_keys=[requester_id], back_populates="sent_requests")
    addressee = relationship("User", foreign_keys=[addressee_id], back_populates="received_requests")
    __table_args__ = (Index("idx_friendship_users", "requester_id", "addressee_id", unique=True),)

class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    user = relationship("User")

class InviteLink(Base):
    __tablename__ = "invite_links"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), unique=True, nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    max_uses = Column(Integer, nullable=True)
    uses = Column(Integer, default=0)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    room = relationship("Room", back_populates="invite_links")
    creator = relationship("User")

class GameStat(Base):
    __tablename__ = "game_stats"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    game = Column(String(30), nullable=False)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    draws = Column(Integer, default=0)
    score = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = relationship("User", back_populates="game_stats")

class ActiveGame(Base):
    __tablename__ = "active_games"
    id = Column(Integer, primary_key=True, index=True)
    game_type = Column(String(30), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    player1_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    player2_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    state = Column(JSON, nullable=False)
    current_turn_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String(20), default="waiting")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
