"""trmsg - API Endpoints"""
import os, uuid, json, mimetypes, secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, desc, func
from pydantic import BaseModel, validator

from server.database.db import (
    get_db, User, Room, RoomMember, Message, FileUpload,
    Friendship, FriendStatus, Notification, Reaction, Poll, PollVote,
    MessageType, RoomType, UserStatus, UserRole, InviteLink, ActiveGame, GameStat
)
from server.auth.auth import hash_password, verify_password, create_access_token, get_current_user
from server.websocket.manager import manager
from server.games.engine import (
    ttt_new_board, ttt_render, chess_new_board, chess_render,
    quiz_new_game, quiz_render_question
)
from server.config import settings

router = APIRouter()

# ── SCHEMAS ───────────────────────────────────────────────────────
class RegisterReq(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    display_name: Optional[str] = None

    @validator("username")
    def val_username(cls, v):
        v = v.strip().lower()
        if not v.replace("_","").replace("-","").isalnum():
            raise ValueError("Only letters, numbers, underscores, hyphens")
        if not 3 <= len(v) <= 32:
            raise ValueError("Must be 3-32 characters")
        return v

    @validator("password")
    def val_password(cls, v):
        if len(v) < 8:
            raise ValueError("Must be at least 8 characters")
        return v

class LoginReq(BaseModel):
    username: str
    password: str

class UpdateProfileReq(BaseModel):
    display_name: Optional[str] = None
    bio: Optional[str] = None
    status_message: Optional[str] = None
    public_key: Optional[str] = None
    avatar_color: Optional[str] = None
    theme: Optional[str] = None

class SetStatusReq(BaseModel):
    status: str
    status_message: Optional[str] = None

class CreateRoomReq(BaseModel):
    name: str
    description: Optional[str] = None
    display_name: Optional[str] = None
    icon: Optional[str] = "💬"
    is_private: bool = False
    topic: Optional[str] = None
    category: Optional[str] = None
    password: Optional[str] = None

class CreatePollReq(BaseModel):
    room: str
    question: str
    options: List[str]
    is_multiple: bool = False
    is_anonymous: bool = True

class AlertReq(BaseModel):
    keyword: str

class DNDReq(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None
    enabled: bool = True

class StartGameReq(BaseModel):
    game_type: str
    opponent: Optional[str] = None
    room: Optional[str] = None
    num_questions: Optional[int] = 5

class AnnounceReq(BaseModel):
    room: str
    content: str

# ── AUTH ──────────────────────────────────────────────────────────
@router.post("/users/register", status_code=201, tags=["auth"])
async def register(req: RegisterReq, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(User).where(User.username == req.username))
    if r.scalar_one_or_none():
        raise HTTPException(400, "Username already taken")
    if req.email:
        r = await db.execute(select(User).where(User.email == req.email))
        if r.scalar_one_or_none():
            raise HTTPException(400, "Email already registered")

    import random
    colors = ["#00ff88","#ff6b6b","#4ecdc4","#45b7d1","#96ceb4","#ffad8e","#dda0dd","#98d8c8"]
    user = User(
        username=req.username, email=req.email,
        hashed_password=hash_password(req.password),
        display_name=req.display_name or req.username,
        avatar_color=random.choice(colors),
    )
    db.add(user)
    await db.flush()

    r = await db.execute(select(Room).where(Room.name == "general"))
    general = r.scalar_one_or_none()
    if not general:
        general = Room(name="general", display_name="General", description="Welcome to trmsg!", icon="👋", category="general")
        db.add(general)
        await db.flush()
    db.add(RoomMember(room_id=general.id, user_id=user.id))
    await db.commit()

    token = create_access_token({"sub": user.username})
    return {"message": "Welcome to trmsg!", "username": user.username, "token": token, "avatar_color": user.avatar_color}


@router.post("/users/login", tags=["auth"])
async def login(req: LoginReq, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(User).where(User.username == req.username.lower().strip()))
    user = r.scalar_one_or_none()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(401, "Invalid credentials")
    if not user.is_active:
        raise HTTPException(403, "Account disabled")
    token = create_access_token({"sub": user.username})
    return {"message": "Login successful", "username": user.username, "display_name": user.display_name, "avatar_color": user.avatar_color, "token": token, "theme": user.theme}


@router.get("/users/me", tags=["users"])
async def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id, "username": current_user.username,
        "display_name": current_user.display_name, "email": current_user.email,
        "bio": current_user.bio, "avatar_color": current_user.avatar_color,
        "status": current_user.status.value if current_user.status else "offline",
        "status_message": current_user.status_message, "theme": current_user.theme,
        "role": current_user.role.value if current_user.role else "member",
        "total_messages": current_user.total_messages, "score": current_user.score or 0,
        "created_at": current_user.created_at.isoformat(), "is_admin": current_user.is_admin,
        "alert_keywords": current_user.alert_keywords or [],
        "dnd_start": current_user.dnd_start, "dnd_end": current_user.dnd_end,
    }


@router.patch("/users/me", tags=["users"])
async def update_profile(req: UpdateProfileReq, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    for field, val in req.dict(exclude_none=True).items():
        setattr(current_user, field, val)
    await db.commit()
    return {"message": "Profile updated"}


@router.post("/users/status", tags=["users"])
async def set_status(req: SetStatusReq, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    status_map = {"online": UserStatus.ONLINE, "away": UserStatus.AWAY, "busy": UserStatus.BUSY, "invisible": UserStatus.INVISIBLE}
    s = status_map.get(req.status.lower())
    if not s:
        raise HTTPException(400, f"Invalid status")
    current_user.status = s
    if req.status_message is not None:
        current_user.status_message = req.status_message
    await db.commit()
    await manager.broadcast_all({"type": "presence", "username": current_user.username, "status": req.status, "status_message": req.status_message, "timestamp": datetime.utcnow().isoformat()})
    return {"message": f"Status: {req.status}"}


@router.post("/users/alert", tags=["users"])
async def add_alert(req: AlertReq, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    keywords = current_user.alert_keywords or []
    if req.keyword not in keywords:
        keywords.append(req.keyword.lower())
        current_user.alert_keywords = keywords
        await db.commit()
    return {"message": f"Alert added for '{req.keyword}'", "keywords": keywords}


@router.delete("/users/alert/{keyword}", tags=["users"])
async def remove_alert(keyword: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    keywords = current_user.alert_keywords or []
    keywords = [k for k in keywords if k != keyword.lower()]
    current_user.alert_keywords = keywords
    await db.commit()
    return {"message": f"Alert removed for '{keyword}'"}


@router.post("/users/dnd", tags=["users"])
async def set_dnd(req: DNDReq, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if req.enabled:
        current_user.dnd_start = req.start
        current_user.dnd_end = req.end
    else:
        current_user.dnd_start = None
        current_user.dnd_end = None
    await db.commit()
    return {"message": "DND updated"}


@router.get("/users/online", tags=["users"])
async def online_users(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(User).where(User.status != UserStatus.OFFLINE))
    users = [u for u in r.scalars().all() if manager.is_online(u.id)]
    return {"users": [{"username": u.username, "display_name": u.display_name, "avatar_color": u.avatar_color, "status": u.status.value if u.status else "offline", "status_message": u.status_message, "role": u.role.value if u.role else "member", "score": u.score or 0} for u in users], "count": len(users)}


@router.get("/users/search", tags=["users"])
async def search_users(q: str = Query(..., min_length=1), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(User).where(and_(User.is_active == True, or_(User.username.ilike(f"%{q}%"), User.display_name.ilike(f"%{q}%")))).limit(20))
    users = r.scalars().all()
    return {"users": [{"username": u.username, "display_name": u.display_name, "avatar_color": u.avatar_color, "is_online": manager.is_online(u.id), "role": u.role.value if u.role else "member"} for u in users]}


@router.get("/users/{username}", tags=["users"])
async def get_user(username: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(User).where(User.username == username.lower()))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    return {"username": user.username, "display_name": user.display_name, "bio": user.bio, "avatar_color": user.avatar_color, "status": user.status.value if user.status else "offline", "status_message": user.status_message, "role": user.role.value if user.role else "member", "total_messages": user.total_messages, "score": user.score or 0, "is_online": manager.is_online(user.id), "last_seen": user.last_seen.isoformat() if user.last_seen else None, "created_at": user.created_at.isoformat()}


# ── ROOMS ─────────────────────────────────────────────────────────
@router.post("/rooms", status_code=201, tags=["rooms"])
async def create_room(req: CreateRoomReq, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    name = req.name.lower().replace(" ", "-")
    r = await db.execute(select(Room).where(Room.name == name))
    if r.scalar_one_or_none():
        raise HTTPException(400, f"Room '{name}' already exists")
    pw_hash = hash_password(req.password) if req.password else None
    room = Room(name=name, display_name=req.display_name or name, description=req.description, topic=req.topic, icon=req.icon or "💬", room_type=RoomType.PRIVATE if req.is_private else RoomType.PUBLIC, owner_id=current_user.id, category=req.category, password_hash=pw_hash)
    db.add(room)
    await db.flush()
    db.add(RoomMember(room_id=room.id, user_id=current_user.id, is_admin=True))
    await db.commit()
    manager.subscribe(current_user.id, name)
    return {"message": f"Room '{name}' created", "name": name, "icon": room.icon}


@router.post("/rooms/{room_name}/join", tags=["rooms"])
async def join_room(room_name: str, password: Optional[str] = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Room).where(Room.name == room_name.lower()))
    room = r.scalar_one_or_none()
    if not room:
        raise HTTPException(404, f"Room not found")
    if room.room_type == RoomType.PRIVATE:
        raise HTTPException(403, "Private room — need an invite")
    if room.password_hash and not (password and verify_password(password, room.password_hash)):
        raise HTTPException(403, "Wrong room password")
    r2 = await db.execute(select(RoomMember).where(and_(RoomMember.room_id == room.id, RoomMember.user_id == current_user.id)))
    if r2.scalar_one_or_none():
        raise HTTPException(400, "Already a member")
    db.add(RoomMember(room_id=room.id, user_id=current_user.id))
    await db.commit()
    manager.subscribe(current_user.id, room.name)
    await manager.broadcast(room.name, {"type": "system", "room": room.name, "content": f"➕ {current_user.display_name or current_user.username} joined #{room.name}", "timestamp": datetime.utcnow().isoformat()})
    return {"message": f"Joined #{room_name}"}


@router.post("/rooms/{room_name}/leave", tags=["rooms"])
async def leave_room(room_name: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(RoomMember).join(Room).where(and_(Room.name == room_name.lower(), RoomMember.user_id == current_user.id)))
    member = r.scalar_one_or_none()
    if not member:
        raise HTTPException(400, "Not a member")
    await db.delete(member)
    await db.commit()
    manager.unsubscribe(current_user.id, room_name.lower())
    await manager.broadcast(room_name.lower(), {"type": "system", "room": room_name.lower(), "content": f"➖ {current_user.display_name or current_user.username} left", "timestamp": datetime.utcnow().isoformat()})
    return {"message": f"Left #{room_name}"}


@router.get("/rooms", tags=["rooms"])
async def list_rooms(category: Optional[str] = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    query = select(Room).where(Room.room_type == RoomType.PUBLIC)
    if category:
        query = query.where(Room.category == category)
    r = await db.execute(query)
    rooms = r.scalars().all()
    return {"rooms": [{"name": rm.name, "display_name": rm.display_name or rm.name, "description": rm.description, "topic": rm.topic, "icon": rm.icon, "category": rm.category, "online": manager.online_in_room(rm.name), "total_messages": rm.total_messages, "has_password": bool(rm.password_hash), "tags": rm.tags} for rm in rooms]}


@router.get("/rooms/my", tags=["rooms"])
async def my_rooms(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Room).join(RoomMember).where(and_(RoomMember.user_id == current_user.id, Room.room_type != RoomType.DIRECT)))
    rooms = r.scalars().all()
    return {"rooms": [{"name": rm.name, "display_name": rm.display_name or rm.name, "icon": rm.icon, "category": rm.category, "online": manager.online_in_room(rm.name)} for rm in rooms]}


@router.get("/rooms/{room_name}/members", tags=["rooms"])
async def room_members(room_name: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(User, RoomMember).join(RoomMember, User.id == RoomMember.user_id).join(Room).where(Room.name == room_name.lower()))
    rows = r.all()
    return {"members": [{"username": u.username, "display_name": u.display_name, "avatar_color": u.avatar_color, "is_admin": m.is_admin, "is_online": manager.is_online(u.id), "role": u.role.value if u.role else "member"} for u, m in rows]}


# ── INVITE LINKS ──────────────────────────────────────────────────
@router.post("/rooms/{room_name}/invite", tags=["rooms"])
async def create_invite(room_name: str, max_uses: Optional[int] = None, expire_hours: Optional[int] = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Room).where(Room.name == room_name.lower()))
    room = r.scalar_one_or_none()
    if not room:
        raise HTTPException(404, "Room not found")
    code = secrets.token_urlsafe(8)
    expires_at = datetime.utcnow() + timedelta(hours=expire_hours) if expire_hours else None
    invite = InviteLink(code=code, room_id=room.id, creator_id=current_user.id, max_uses=max_uses, expires_at=expires_at)
    db.add(invite)
    await db.commit()
    return {"code": code, "room": room_name, "invite_url": f"trmsg invite {code}", "max_uses": max_uses, "expires_at": expires_at.isoformat() if expires_at else None}


@router.post("/invite/use/{code}", tags=["rooms"])
async def use_invite(code: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(InviteLink).where(InviteLink.code == code))
    invite = r.scalar_one_or_none()
    if not invite:
        raise HTTPException(404, "Invalid invite code")
    if invite.expires_at and datetime.utcnow() > invite.expires_at:
        raise HTTPException(400, "Invite link expired")
    if invite.max_uses and invite.uses >= invite.max_uses:
        raise HTTPException(400, "Invite link max uses reached")
    room_r = await db.execute(select(Room).where(Room.id == invite.room_id))
    room = room_r.scalar_one_or_none()
    if not room:
        raise HTTPException(404, "Room not found")
    existing = await db.execute(select(RoomMember).where(and_(RoomMember.room_id == room.id, RoomMember.user_id == current_user.id)))
    if not existing.scalar_one_or_none():
        db.add(RoomMember(room_id=room.id, user_id=current_user.id))
        invite.uses = (invite.uses or 0) + 1
        await db.commit()
        manager.subscribe(current_user.id, room.name)
    return {"message": f"Joined #{room.name} via invite!", "room": room.name}


# ── MESSAGES ──────────────────────────────────────────────────────
@router.get("/messages/history/{room_name}", tags=["messages"])
async def get_history(room_name: str, limit: int = Query(50, le=200), offset: int = Query(0, ge=0), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Room).join(RoomMember).where(and_(Room.name == room_name.lower(), RoomMember.user_id == current_user.id)))
    room = r.scalar_one_or_none()
    if not room:
        raise HTTPException(403, "Not a member")
    r = await db.execute(select(Message, User.username, User.display_name, User.avatar_color).join(User, Message.sender_id == User.id).where(and_(Message.room_id == room.id, Message.is_deleted == False)).order_by(desc(Message.created_at)).limit(limit).offset(offset))
    rows = r.all()
    messages = []
    for msg, uname, dname, color in reversed(rows):
        m = {"id": msg.id, "sender": uname, "display_name": dname, "avatar_color": color, "content": msg.content, "message_type": msg.message_type.value, "code_language": msg.code_language, "is_pinned": msg.is_pinned, "timestamp": msg.created_at.isoformat(), "edited_at": msg.edited_at.isoformat() if msg.edited_at else None, "burn_at": msg.burn_at.isoformat() if msg.burn_at else None}
        r2 = await db.execute(select(Reaction).where(Reaction.message_id == msg.id))
        emoji_counts = {}
        for rx in r2.scalars().all():
            emoji_counts[rx.emoji] = emoji_counts.get(rx.emoji, 0) + 1
        m["reactions"] = emoji_counts
        if msg.reply_to_id:
            rr = await db.execute(select(Message, User.username).join(User, Message.sender_id == User.id).where(Message.id == msg.reply_to_id))
            row = rr.first()
            if row:
                rm, runame = row
                m["reply_to"] = {"id": rm.id, "sender": runame, "content": (rm.content or "")[:100]}
        messages.append(m)
    return {"room": room_name, "messages": messages}


@router.get("/messages/search/{room_name}", tags=["messages"])
async def search_messages(room_name: str, q: str = Query(..., min_length=1), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Room).join(RoomMember).where(and_(Room.name == room_name.lower(), RoomMember.user_id == current_user.id)))
    room = r.scalar_one_or_none()
    if not room:
        raise HTTPException(403, "Not a member")
    r = await db.execute(select(Message, User.username).join(User, Message.sender_id == User.id).where(and_(Message.room_id == room.id, Message.content.ilike(f"%{q}%"), Message.is_deleted == False)).order_by(desc(Message.created_at)).limit(20))
    results = [{"id": m.id, "sender": un, "content": m.content, "timestamp": m.created_at.isoformat()} for m, un in r.all()]
    return {"results": results, "count": len(results)}


@router.delete("/messages/{message_id}", tags=["messages"])
async def delete_message(message_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Message).where(Message.id == message_id))
    msg = r.scalar_one_or_none()
    if not msg:
        raise HTTPException(404, "Message not found")
    if msg.sender_id != current_user.id and not current_user.is_admin:
        raise HTTPException(403, "Cannot delete")
    msg.is_deleted = True
    msg.content = "[deleted]"
    await db.commit()
    room_r = await db.execute(select(Room).where(Room.id == msg.room_id))
    room = room_r.scalar_one_or_none()
    if room:
        await manager.broadcast(room.name, {"type": "message_deleted", "message_id": message_id, "room": room.name})
    return {"message": "Deleted"}


@router.patch("/messages/{message_id}", tags=["messages"])
async def edit_message(message_id: int, content: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Message).where(Message.id == message_id))
    msg = r.scalar_one_or_none()
    if not msg or msg.sender_id != current_user.id:
        raise HTTPException(403, "Cannot edit")
    msg.content = content
    msg.edited_at = datetime.utcnow()
    await db.commit()
    room_r = await db.execute(select(Room).where(Room.id == msg.room_id))
    room = room_r.scalar_one_or_none()
    if room:
        await manager.broadcast(room.name, {"type": "message_edited", "message_id": message_id, "content": content, "room": room.name})
    return {"message": "Edited"}


# ── FILES ─────────────────────────────────────────────────────────
@router.post("/files/upload", tags=["files"])
async def upload_file(file: UploadFile = File(...), room: Optional[str] = None, recipient: Optional[str] = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ext = Path(file.filename).suffix.lower().lstrip(".")
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"File type '.{ext}' not allowed")
    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(413, "File too large (max 200MB)")
    safe_name = f"{uuid.uuid4().hex}.{ext}"
    file_path = Path(settings.UPLOAD_DIR) / safe_name
    file_path.write_bytes(content)
    mime = mimetypes.guess_type(file.filename)[0] or "application/octet-stream"
    db_file = FileUpload(filename=safe_name, original_filename=file.filename, file_size=len(content), mime_type=mime, storage_path=str(file_path), uploader_id=current_user.id)
    db.add(db_file)
    u = await db.execute(select(User).where(User.id == current_user.id))
    usr = u.scalar_one_or_none()
    if usr:
        usr.total_files = (usr.total_files or 0) + 1
    await db.flush()

    target_room_name = None
    if room:
        r = await db.execute(select(Room).join(RoomMember).where(and_(Room.name == room.lower(), RoomMember.user_id == current_user.id)))
        target_room = r.scalar_one_or_none()
        if target_room:
            target_room_name = target_room.name
            is_image = mime.startswith("image/")
            db.add(Message(room_id=target_room.id, sender_id=current_user.id, content=f"{'🖼' if is_image else '📎'} {file.filename} ({_fmt_size(len(content))})", message_type=MessageType.IMAGE if is_image else MessageType.FILE, file_id=db_file.id))
    elif recipient:
        r = await db.execute(select(User).where(User.username == recipient.lower()))
        other = r.scalar_one_or_none()
        if other:
            dm_name = "dm_" + "_".join(sorted([current_user.username, other.username]))
            r2 = await db.execute(select(Room).where(Room.name == dm_name))
            dm = r2.scalar_one_or_none()
            if not dm:
                dm = Room(name=dm_name, room_type=RoomType.DIRECT)
                db.add(dm)
                await db.flush()
                db.add(RoomMember(room_id=dm.id, user_id=current_user.id))
                db.add(RoomMember(room_id=dm.id, user_id=other.id))
            target_room_name = dm_name
            is_image = mime.startswith("image/")
            db.add(Message(room_id=dm.id, sender_id=current_user.id, content=f"{'🖼' if is_image else '📎'} {file.filename}", message_type=MessageType.IMAGE if is_image else MessageType.FILE, file_id=db_file.id))

    await db.commit()
    await db.refresh(db_file)
    if target_room_name:
        await manager.broadcast(target_room_name, {"type": "message", "room": target_room_name, "sender": current_user.username, "content": f"📎 {file.filename}", "message_type": "file", "file": {"id": db_file.id, "filename": file.filename, "size": len(content), "mime_type": mime}, "timestamp": datetime.utcnow().isoformat()})
    return {"file_id": db_file.id, "filename": file.filename, "size": len(content), "mime_type": mime, "download_url": f"/api/v1/files/{db_file.id}/download"}


@router.get("/files/{file_id}/download", tags=["files"])
async def download_file(file_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(FileUpload).where(FileUpload.id == file_id))
    f = r.scalar_one_or_none()
    if not f or not os.path.exists(f.storage_path):
        raise HTTPException(404, "File not found")
    f.download_count = (f.download_count or 0) + 1
    await db.commit()
    def stream():
        with open(f.storage_path, "rb") as fp:
            while chunk := fp.read(65536):
                yield chunk
    return StreamingResponse(stream(), media_type=f.mime_type or "application/octet-stream", headers={"Content-Disposition": f'attachment; filename="{f.original_filename}"', "Content-Length": str(f.file_size)})


# ── FRIENDS ───────────────────────────────────────────────────────
@router.post("/friends/add/{username}", tags=["friends"])
async def add_friend(username: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if username.lower() == current_user.username:
        raise HTTPException(400, "Cannot add yourself")
    r = await db.execute(select(User).where(User.username == username.lower()))
    target = r.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "User not found")
    r = await db.execute(select(Friendship).where(or_(and_(Friendship.requester_id == current_user.id, Friendship.addressee_id == target.id), and_(Friendship.requester_id == target.id, Friendship.addressee_id == current_user.id))))
    existing = r.scalar_one_or_none()
    if existing:
        if existing.status == FriendStatus.ACCEPTED:
            raise HTTPException(400, "Already friends")
        elif existing.status == FriendStatus.PENDING:
            raise HTTPException(400, "Request already pending")
    db.add(Friendship(requester_id=current_user.id, addressee_id=target.id))
    await db.commit()
    await manager.send(target.id, {"type": "friend_request", "from": current_user.username, "display_name": current_user.display_name, "avatar_color": current_user.avatar_color, "timestamp": datetime.utcnow().isoformat()})
    return {"message": f"Friend request sent to {username}"}


@router.post("/friends/accept/{username}", tags=["friends"])
async def accept_friend(username: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(User).where(User.username == username.lower()))
    requester = r.scalar_one_or_none()
    if not requester:
        raise HTTPException(404, "User not found")
    r = await db.execute(select(Friendship).where(and_(Friendship.requester_id == requester.id, Friendship.addressee_id == current_user.id, Friendship.status == FriendStatus.PENDING)))
    f = r.scalar_one_or_none()
    if not f:
        raise HTTPException(404, "No pending request")
    f.status = FriendStatus.ACCEPTED
    dm_name = "dm_" + "_".join(sorted([current_user.username, requester.username]))
    r2 = await db.execute(select(Room).where(Room.name == dm_name))
    if not r2.scalar_one_or_none():
        dm = Room(name=dm_name, room_type=RoomType.DIRECT)
        db.add(dm)
        await db.flush()
        db.add(RoomMember(room_id=dm.id, user_id=current_user.id))
        db.add(RoomMember(room_id=dm.id, user_id=requester.id))
    await db.commit()
    await manager.send(requester.id, {"type": "friend_accepted", "by": current_user.username, "timestamp": datetime.utcnow().isoformat()})
    return {"message": f"Now friends with {username}!"}


@router.post("/friends/reject/{username}", tags=["friends"])
async def reject_friend(username: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(User).where(User.username == username.lower()))
    requester = r.scalar_one_or_none()
    if not requester:
        raise HTTPException(404, "User not found")
    r = await db.execute(select(Friendship).where(and_(Friendship.requester_id == requester.id, Friendship.addressee_id == current_user.id, Friendship.status == FriendStatus.PENDING)))
    f = r.scalar_one_or_none()
    if not f:
        raise HTTPException(404, "No request")
    f.status = FriendStatus.REJECTED
    await db.commit()
    return {"message": "Rejected"}


@router.get("/friends/list", tags=["friends"])
async def list_friends(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Friendship).where(and_(or_(Friendship.requester_id == current_user.id, Friendship.addressee_id == current_user.id), Friendship.status == FriendStatus.ACCEPTED)))
    friends = []
    for f in r.scalars().all():
        fid = f.addressee_id if f.requester_id == current_user.id else f.requester_id
        u = await db.execute(select(User).where(User.id == fid))
        user = u.scalar_one_or_none()
        if user:
            friends.append({"username": user.username, "display_name": user.display_name, "avatar_color": user.avatar_color, "status": user.status.value if user.status else "offline", "status_message": user.status_message, "is_online": manager.is_online(user.id), "last_seen": user.last_seen.isoformat() if user.last_seen else None})
    return {"friends": friends}


@router.get("/friends/requests", tags=["friends"])
async def friend_requests(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Friendship).where(and_(Friendship.addressee_id == current_user.id, Friendship.status == FriendStatus.PENDING)))
    requests = []
    for f in r.scalars().all():
        u = await db.execute(select(User).where(User.id == f.requester_id))
        user = u.scalar_one_or_none()
        if user:
            requests.append({"username": user.username, "display_name": user.display_name, "avatar_color": user.avatar_color, "sent_at": f.created_at.isoformat()})
    return {"requests": requests}


# ── POLLS ─────────────────────────────────────────────────────────
@router.post("/polls", tags=["polls"])
async def create_poll(req: CreatePollReq, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not 2 <= len(req.options) <= 10:
        raise HTTPException(400, "Need 2-10 options")
    r = await db.execute(select(Room).join(RoomMember).where(and_(Room.name == req.room.lower(), RoomMember.user_id == current_user.id)))
    room = r.scalar_one_or_none()
    if not room:
        raise HTTPException(403, "Not a member")
    poll_content = f"📊 **{req.question}**\n" + "\n".join(f"  {i+1}. {opt}" for i, opt in enumerate(req.options))
    msg = Message(room_id=room.id, sender_id=current_user.id, content=poll_content, message_type=MessageType.POLL)
    db.add(msg)
    await db.flush()
    poll = Poll(message_id=msg.id, question=req.question, options=req.options, is_multiple=req.is_multiple, is_anonymous=req.is_anonymous)
    db.add(poll)
    await db.commit()
    await manager.broadcast(room.name, {"type": "poll", "message_id": msg.id, "poll_id": poll.id, "room": room.name, "sender": current_user.username, "question": req.question, "options": req.options, "is_multiple": req.is_multiple, "is_anonymous": req.is_anonymous, "vote_counts": {}, "timestamp": datetime.utcnow().isoformat()})
    return {"poll_id": poll.id, "message_id": msg.id}


# ── GAMES ─────────────────────────────────────────────────────────
@router.post("/games/start", tags=["games"])
async def start_game(req: StartGameReq, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if req.game_type not in ["ttt", "chess", "quiz"]:
        raise HTTPException(400, "Game must be: ttt, chess, quiz")

    player2_id = None
    if req.opponent:
        r = await db.execute(select(User).where(User.username == req.opponent.lower()))
        opp = r.scalar_one_or_none()
        if not opp:
            raise HTTPException(404, f"User '{req.opponent}' not found")
        player2_id = opp.id

    if req.game_type == "ttt":
        state = ttt_new_board()
    elif req.game_type == "chess":
        state = chess_new_board()
    else:
        state = quiz_new_game(req.num_questions or 5)

    game = ActiveGame(
        game_type=req.game_type, player1_id=current_user.id,
        player2_id=player2_id, state=state,
        current_turn_id=current_user.id,
        room_id=None, status="waiting" if player2_id else "active",
    )
    db.add(game)
    await db.flush()

    room_name = req.room or "general"

    if req.game_type == "ttt":
        board_str = ttt_render(state["board"])
        intro = f"🎮 **TicTacToe** started by {current_user.username}!\nGame ID: {game.id}\n\n{board_str}\n\nMake a move: /move {game.id} <1-9>"
    elif req.game_type == "chess":
        board_str = chess_render(state["board"])
        intro = f"♟ **Chess** started by {current_user.username}!\nGame ID: {game.id}\n\n{board_str}\n\nMake a move: /move {game.id} e2e4"
    else:
        q = state["questions"][0]
        intro = f"🧠 **Quiz Battle** started by {current_user.username}! ({req.num_questions} questions)\nGame ID: {game.id}\n\n{quiz_render_question(q, 1, req.num_questions or 5)}"

    r = await db.execute(select(Room).where(Room.name == room_name))
    room = r.scalar_one_or_none()
    if room:
        db.add(Message(room_id=room.id, sender_id=current_user.id, content=intro, message_type=MessageType.SYSTEM))

    await db.commit()

    if room_name:
        await manager.broadcast(room_name, {"type": "game_started", "game_type": req.game_type, "game_id": game.id, "room": room_name, "starter": current_user.username, "opponent": req.opponent, "intro": intro, "timestamp": datetime.utcnow().isoformat()})

    if player2_id:
        await manager.send(player2_id, {"type": "game_invite", "game_type": req.game_type, "game_id": game.id, "from": current_user.username, "room": room_name})

    return {"game_id": game.id, "game_type": req.game_type, "message": intro}


@router.get("/games/leaderboard", tags=["games"])
async def leaderboard(game: Optional[str] = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Overall score leaderboard
    r = await db.execute(select(User).where(User.is_active == True).order_by(desc(User.score)).limit(20))
    users = r.scalars().all()
    overall = [{"rank": i+1, "username": u.username, "display_name": u.display_name, "avatar_color": u.avatar_color, "score": u.score or 0, "is_online": manager.is_online(u.id)} for i, u in enumerate(users)]

    game_stats = {}
    if game:
        r = await db.execute(select(GameStat, User.username, User.avatar_color).join(User).where(GameStat.game == game).order_by(desc(GameStat.score)).limit(10))
        game_stats[game] = [{"rank": i+1, "username": un, "avatar_color": color, "wins": gs.wins, "losses": gs.losses, "score": gs.score} for i, (gs, un, color) in enumerate(r.all())]

    return {"overall": overall, "game_stats": game_stats}


@router.get("/users/{username}/stats", tags=["users"])
async def user_stats(username: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(User).where(User.username == username.lower()))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    gs_r = await db.execute(select(GameStat).where(GameStat.user_id == user.id))
    game_stats = {gs.game: {"wins": gs.wins, "losses": gs.losses, "draws": gs.draws, "score": gs.score} for gs in gs_r.scalars().all()}

    rank_r = await db.execute(select(func.count(User.id)).where(User.score > (user.score or 0)))
    rank = (await db.scalar(select(func.count(User.id)).where(User.score > (user.score or 0)))) + 1

    return {"username": user.username, "display_name": user.display_name, "avatar_color": user.avatar_color, "total_messages": user.total_messages or 0, "total_files": user.total_files or 0, "total_reactions": user.total_reactions or 0, "score": user.score or 0, "rank": rank, "game_stats": game_stats, "member_since": user.created_at.isoformat(), "last_seen": user.last_seen.isoformat() if user.last_seen else None}


# ── STATS ─────────────────────────────────────────────────────────
@router.get("/stats", tags=["stats"])
async def server_stats(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    user_count = await db.scalar(select(func.count(User.id)).where(User.is_active == True))
    room_count = await db.scalar(select(func.count(Room.id)))
    msg_count = await db.scalar(select(func.count(Message.id)).where(Message.is_deleted == False))
    file_count = await db.scalar(select(func.count(FileUpload.id)))
    game_count = await db.scalar(select(func.count(ActiveGame.id)))
    return {"users": user_count, "rooms": room_count, "messages": msg_count, "files": file_count, "games_played": game_count, "online_now": manager.online_count()}


def _fmt_size(size: int) -> str:
    for unit in ["B","KB","MB","GB"]:
        if size < 1024: return f"{size:.1f}{unit}"
        size //= 1024
    return f"{size:.1f}GB"
