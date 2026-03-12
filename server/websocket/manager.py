"""trmsg - WebSocket Manager"""
import json
import asyncio
import secrets
from datetime import datetime, timedelta
from typing import Dict, Set, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from server.database.db import (
    AsyncSessionLocal, User, Message, Room, RoomMember,
    MessageType, Notification, Reaction, Poll, PollVote,
    ActiveGame, GameStat, UserStatus
)
from server.auth.auth import get_user_from_token
from server.games.engine import (
    ttt_new_board, ttt_render, ttt_move, ttt_ai_move,
    chess_new_board, chess_render, chess_make_move,
    quiz_new_game, quiz_answer, quiz_next_question,
    quiz_render_question, quiz_render_scores,
)
from server.ai.gemini import ask_gemini, summarize_messages, translate_text, explain_code
from sqlalchemy import select, and_, desc

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active: Dict[int, WebSocket] = {}
        self.rooms: Dict[str, Set[int]] = {}
        self.user_rooms: Dict[int, Set[str]] = {}
        self.typing: Dict[str, Dict[int, float]] = {}

    async def connect(self, user_id: int, ws: WebSocket):
        await ws.accept()
        self.active[user_id] = ws
        self.user_rooms.setdefault(user_id, set())
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(User).where(User.id == user_id))
            user = r.scalar_one_or_none()
            if user:
                user.status = UserStatus.ONLINE
                user.last_seen = datetime.utcnow()
                await db.commit()
                await self._broadcast_presence(user.username, "online", user.status_message)

    async def disconnect(self, user_id: int):
        self.active.pop(user_id, None)
        for room in list(self.user_rooms.get(user_id, [])):
            self.rooms.get(room, set()).discard(user_id)
        self.user_rooms.pop(user_id, None)
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(User).where(User.id == user_id))
            user = r.scalar_one_or_none()
            if user:
                user.status = UserStatus.OFFLINE
                user.last_seen = datetime.utcnow()
                await db.commit()
                await self._broadcast_presence(user.username, "offline", None)

    def subscribe(self, user_id: int, room: str):
        self.rooms.setdefault(room, set()).add(user_id)
        self.user_rooms.setdefault(user_id, set()).add(room)

    def unsubscribe(self, user_id: int, room: str):
        self.rooms.get(room, set()).discard(user_id)
        self.user_rooms.get(user_id, set()).discard(room)

    async def send(self, user_id: int, msg: dict):
        ws = self.active.get(user_id)
        if ws:
            try:
                await ws.send_text(json.dumps(msg, default=str))
            except:
                pass

    async def broadcast(self, room: str, msg: dict, exclude: Optional[int] = None):
        for uid in list(self.rooms.get(room, [])):
            if uid != exclude:
                await self.send(uid, msg)

    async def broadcast_all(self, msg: dict, exclude: Optional[int] = None):
        for uid in list(self.active.keys()):
            if uid != exclude:
                await self.send(uid, msg)

    def is_online(self, user_id: int) -> bool:
        return user_id in self.active

    def online_count(self) -> int:
        return len(self.active)

    def online_in_room(self, room: str) -> int:
        return len(self.rooms.get(room, set()))

    async def _broadcast_presence(self, username: str, status: str, status_message):
        await self.broadcast_all({
            "type": "presence",
            "username": username,
            "status": status,
            "status_message": status_message,
            "timestamp": datetime.utcnow().isoformat(),
        })

    def set_typing(self, room: str, user_id: int):
        self.typing.setdefault(room, {})[user_id] = datetime.utcnow().timestamp()

    def clear_typing(self, room: str, user_id: int):
        self.typing.get(room, {}).pop(user_id, None)

manager = ConnectionManager()

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(default=None)):
    if not token:
        await websocket.accept()
        await websocket.close(code=4001, reason="No token")
        return

    async with AsyncSessionLocal() as db:
        user = await get_user_from_token(token, db)
        if not user:
            await websocket.accept()
            await websocket.close(code=4001, reason="Invalid token")
            return
        user_id, username = user.id, user.username

    await manager.connect(user_id, websocket)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Room).join(RoomMember).where(RoomMember.user_id == user_id))
        for room in result.scalars().all():
            manager.subscribe(user_id, room.name)
        await _deliver_offline(user_id, db)

    await manager.send(user_id, {
        "type": "connected",
        "username": username,
        "online_count": manager.online_count(),
        "timestamp": datetime.utcnow().isoformat(),
    })

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                await _route(user_id, username, msg)
            except json.JSONDecodeError:
                await manager.send(user_id, {"type": "error", "message": "Invalid JSON"})
    except WebSocketDisconnect:
        await manager.disconnect(user_id)


async def _route(user_id: int, username: str, msg: dict):
    t = msg.get("type")
    handlers = {
        "chat": _handle_chat,
        "join_room": lambda uid, un, m: _quick(uid, un, m, "join"),
        "leave_room": lambda uid, un, m: _quick(uid, un, m, "leave"),
        "typing_start": _handle_typing_start,
        "typing_stop": _handle_typing_stop,
        "react": _handle_react,
        "unreact": _handle_unreact,
        "poll_vote": _handle_poll_vote,
        "game_action": _handle_game,
        "ping": lambda uid, un, m: manager.send(uid, {"type": "pong"}),
    }
    handler = handlers.get(t)
    if handler:
        await handler(user_id, username, msg)


async def _quick(user_id, username, msg, action):
    room = msg.get("room")
    if not room:
        return
    if action == "join":
        manager.subscribe(user_id, room)
        await manager.send(user_id, {"type": "joined_room", "room": room})
    else:
        manager.unsubscribe(user_id, room)


async def _handle_chat(user_id: int, username: str, msg: dict):
    room_name = msg.get("room", "").strip()
    content = msg.get("content", "").strip()
    if not room_name or not content:
        return
    if len(content) > 4000:
        await manager.send(user_id, {"type": "error", "message": "Message too long"})
        return

    # Check if AI command
    if content.startswith("/ai "):
        await _handle_ai(user_id, username, room_name, content[4:])
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Room).join(RoomMember).where(
                and_(Room.name == room_name, RoomMember.user_id == user_id)
            )
        )
        room = result.scalar_one_or_none()
        if not room:
            await manager.send(user_id, {"type": "error", "message": f"Not a member of #{room_name}"})
            return

        burn_seconds = msg.get("burn_after")
        burn_at = None
        if burn_seconds:
            try:
                burn_at = datetime.utcnow() + timedelta(seconds=int(burn_seconds))
            except:
                pass

        msg_type = MessageType.BURN if burn_at else MessageType.TEXT
        if msg.get("code_language"):
            msg_type = MessageType.CODE

        message = Message(
            room_id=room.id,
            sender_id=user_id,
            content=content,
            message_type=msg_type,
            reply_to_id=msg.get("reply_to"),
            burn_at=burn_at,
            code_language=msg.get("code_language"),
        )
        db.add(message)

        sender_result = await db.execute(select(User).where(User.id == user_id))
        sender = sender_result.scalar_one_or_none()
        if sender:
            sender.total_messages = (sender.total_messages or 0) + 1
        room.total_messages = (room.total_messages or 0) + 1

        await db.flush()

        # Check keyword alerts for room members
        members_result = await db.execute(select(RoomMember).where(RoomMember.room_id == room.id))
        for member in members_result.scalars().all():
            if member.user_id == user_id:
                continue
            u_result = await db.execute(select(User).where(User.id == member.user_id))
            u = u_result.scalar_one_or_none()
            if u:
                keywords = u.alert_keywords or []
                for kw in keywords:
                    if kw.lower() in content.lower():
                        db.add(Notification(
                            user_id=u.id,
                            type="keyword_alert",
                            content=json.dumps({"keyword": kw, "room": room_name, "sender": username, "preview": content[:80]}),
                        ))
                        break
                if not manager.is_online(u.id) and member.notifications:
                    db.add(Notification(
                        user_id=u.id,
                        type="message",
                        content=json.dumps({"room": room_name, "sender": username, "preview": content[:80], "message_id": message.id}),
                    ))

        await db.commit()

        reply_data = None
        if msg.get("reply_to"):
            r = await db.execute(select(Message).where(Message.id == msg["reply_to"]))
            rm = r.scalar_one_or_none()
            if rm:
                ru = await db.execute(select(User).where(User.id == rm.sender_id))
                ruser = ru.scalar_one_or_none()
                reply_data = {"id": rm.id, "sender": ruser.username if ruser else "?", "content": (rm.content or "")[:100]}

    manager.clear_typing(room_name, user_id)

    out = {
        "type": "message",
        "id": message.id,
        "room": room_name,
        "sender": username,
        "content": content,
        "message_type": msg_type.value,
        "reply_to": reply_data,
        "code_language": msg.get("code_language"),
        "burn_after": burn_seconds,
        "timestamp": message.created_at.isoformat(),
    }

    await manager.broadcast(room_name, out)

    # Schedule burn
    if burn_at:
        asyncio.create_task(_burn_message(message.id, room_name, burn_seconds))


async def _burn_message(msg_id: int, room_name: str, seconds: int):
    await asyncio.sleep(int(seconds))
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Message).where(Message.id == msg_id))
        msg = r.scalar_one_or_none()
        if msg:
            msg.is_deleted = True
            msg.content = "💥 [message self-destructed]"
            await db.commit()
    await manager.broadcast(room_name, {
        "type": "message_burned",
        "message_id": msg_id,
        "room": room_name,
        "timestamp": datetime.utcnow().isoformat(),
    })


async def _handle_ai(user_id: int, username: str, room_name: str, query: str):
    await manager.broadcast(room_name, {
        "type": "system",
        "room": room_name,
        "content": f"🤖 TRM-AI thinking...",
        "timestamp": datetime.utcnow().isoformat(),
    })
    parts = query.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    if cmd == "summarize":
        async with AsyncSessionLocal() as db:
            r = await db.execute(
                select(Message, User.username).join(User, Message.sender_id == User.id)
                .join(Room).where(Room.name == room_name)
                .order_by(desc(Message.created_at)).limit(30)
            )
            msgs = [{"sender": un, "content": m.content or ""} for m, un in reversed(r.all())]
        response = await summarize_messages(msgs)
    elif cmd == "translate":
        lang_parts = rest.split(maxsplit=1)
        if len(lang_parts) < 2:
            response = "Usage: /ai translate <language> <text>"
        else:
            response = await translate_text(lang_parts[1], lang_parts[0])
    elif cmd == "explain":
        response = await explain_code(rest)
    elif cmd == "roast":
        target = rest.strip() or username
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(User).where(User.username == target))
            u = r.scalar_one_or_none()
            stats = {"messages": u.total_messages if u else 0, "files": u.total_files if u else 0}
        from server.ai.gemini import roast_user
        response = await roast_user(target, stats)
    else:
        response = await ask_gemini(query)

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Room).where(Room.name == room_name))
        room = r.scalar_one_or_none()
        if room:
            db.add(Message(room_id=room.id, sender_id=user_id, content=f"🤖 {response}", message_type=MessageType.SYSTEM))
            await db.commit()

    await manager.broadcast(room_name, {
        "type": "ai_response",
        "room": room_name,
        "query": query,
        "response": response,
        "timestamp": datetime.utcnow().isoformat(),
    })


async def _handle_typing_start(user_id: int, username: str, msg: dict):
    room = msg.get("room")
    if room:
        manager.set_typing(room, user_id)
        await manager.broadcast(room, {"type": "typing", "room": room, "username": username, "is_typing": True}, exclude=user_id)

async def _handle_typing_stop(user_id: int, username: str, msg: dict):
    room = msg.get("room")
    if room:
        manager.clear_typing(room, user_id)
        await manager.broadcast(room, {"type": "typing", "room": room, "username": username, "is_typing": False}, exclude=user_id)


async def _handle_react(user_id: int, username: str, msg: dict):
    message_id = msg.get("message_id")
    emoji = msg.get("emoji", "")
    if not message_id or not emoji:
        return
    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(Reaction).where(and_(Reaction.message_id == message_id, Reaction.user_id == user_id, Reaction.emoji == emoji)))
        if not existing.scalar_one_or_none():
            db.add(Reaction(message_id=message_id, user_id=user_id, emoji=emoji))
            u = await db.execute(select(User).where(User.id == user_id))
            user = u.scalar_one_or_none()
            if user:
                user.total_reactions = (user.total_reactions or 0) + 1
            await db.commit()
        m = await db.execute(select(Message).where(Message.id == message_id))
        msg_obj = m.scalar_one_or_none()
        if msg_obj:
            r = await db.execute(select(Room).where(Room.id == msg_obj.room_id))
            room = r.scalar_one_or_none()
            if room:
                await manager.broadcast(room.name, {"type": "reaction", "message_id": message_id, "emoji": emoji, "username": username, "action": "add"})


async def _handle_unreact(user_id: int, username: str, msg: dict):
    message_id = msg.get("message_id")
    emoji = msg.get("emoji", "")
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Reaction).where(and_(Reaction.message_id == message_id, Reaction.user_id == user_id, Reaction.emoji == emoji)))
        reaction = r.scalar_one_or_none()
        if reaction:
            await db.delete(reaction)
            await db.commit()
            m = await db.execute(select(Message).where(Message.id == message_id))
            msg_obj = m.scalar_one_or_none()
            if msg_obj:
                room_r = await db.execute(select(Room).where(Room.id == msg_obj.room_id))
                room = room_r.scalar_one_or_none()
                if room:
                    await manager.broadcast(room.name, {"type": "reaction", "message_id": message_id, "emoji": emoji, "username": username, "action": "remove"})


async def _handle_poll_vote(user_id: int, username: str, msg: dict):
    poll_id = msg.get("poll_id")
    option_index = msg.get("option_index")
    if poll_id is None or option_index is None:
        return
    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(PollVote).where(and_(PollVote.poll_id == poll_id, PollVote.user_id == user_id)))
        if not existing.scalar_one_or_none():
            db.add(PollVote(poll_id=poll_id, user_id=user_id, option_index=option_index))
            await db.commit()
            poll_r = await db.execute(select(Poll).where(Poll.id == poll_id))
            poll = poll_r.scalar_one_or_none()
            if poll:
                votes = await db.execute(select(PollVote).where(PollVote.poll_id == poll_id))
                all_votes = votes.scalars().all()
                counts = {}
                for v in all_votes:
                    counts[v.option_index] = counts.get(v.option_index, 0) + 1
                m_r = await db.execute(select(Message).where(Message.id == poll.message_id))
                m = m_r.scalar_one_or_none()
                if m:
                    room_r = await db.execute(select(Room).where(Room.id == m.room_id))
                    room = room_r.scalar_one_or_none()
                    if room:
                        await manager.broadcast(room.name, {"type": "poll_update", "poll_id": poll_id, "vote_counts": counts, "total_votes": len(all_votes)})


async def _handle_game(user_id: int, username: str, msg: dict):
    action = msg.get("action")
    game_id = msg.get("game_id")
    room_name = msg.get("room")

    if action == "move_ttt":
        await _game_ttt_move(user_id, username, game_id, msg.get("position"), room_name)
    elif action == "move_chess":
        await _game_chess_move(user_id, username, game_id, msg.get("move"), room_name)
    elif action == "quiz_answer":
        await _game_quiz_answer(user_id, username, game_id, msg.get("answer"), room_name)


async def _game_ttt_move(user_id, username, game_id, position, room_name):
    if position is None:
        return
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(ActiveGame).where(ActiveGame.id == game_id))
        game = r.scalar_one_or_none()
        if not game or game.status != "active":
            return

        state = game.state
        is_p1 = game.player1_id == user_id
        symbol = "X" if is_p1 else "O"

        if game.current_turn_id != user_id:
            await manager.send(user_id, {"type": "error", "message": "Not your turn!"})
            return

        new_state, msg_out = ttt_move(state, int(position) - 1, symbol)
        game.state = new_state
        game.updated_at = datetime.utcnow()

        board_str = ttt_render(new_state["board"])
        out = {
            "type": "game_update",
            "game_type": "ttt",
            "game_id": game_id,
            "board": board_str,
            "room": room_name,
            "player": username,
            "move": position,
        }

        if new_state["status"] == "finished":
            game.status = "finished"
            out["winner"] = username
            out["message"] = f"🎉 {username} wins TicTacToe!"
            await _update_game_stats(db, game.player1_id, game.player2_id, "ttt", user_id)
        elif new_state["status"] == "draw":
            game.status = "finished"
            out["message"] = "🤝 It's a draw!"
        else:
            next_player = game.player2_id if is_p1 else game.player1_id
            game.current_turn_id = next_player
            p_result = await db.execute(select(User).where(User.id == next_player))
            p = p_result.scalar_one_or_none()
            out["next_turn"] = p.username if p else "?"

        await db.commit()
        if room_name:
            await manager.broadcast(room_name, out)


async def _game_chess_move(user_id, username, game_id, move_str, room_name):
    if not move_str:
        return
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(ActiveGame).where(ActiveGame.id == game_id))
        game = r.scalar_one_or_none()
        if not game or game.status != "active":
            return

        if game.current_turn_id != user_id:
            await manager.send(user_id, {"type": "error", "message": "Not your turn!"})
            return

        color = "w" if game.player1_id == user_id else "b"
        new_state, msg_out = chess_make_move(game.state, move_str, color)
        game.state = new_state
        game.updated_at = datetime.utcnow()
        board_str = chess_render(new_state["board"])

        out = {"type": "game_update", "game_type": "chess", "game_id": game_id, "board": board_str, "room": room_name, "player": username, "move": move_str}

        if new_state["status"] == "finished":
            game.status = "finished"
            out["message"] = f"♟ {username} wins Chess! Checkmate!"
            await _update_game_stats(db, game.player1_id, game.player2_id, "chess", user_id)
        else:
            next_id = game.player2_id if game.player1_id == user_id else game.player1_id
            game.current_turn_id = next_id
            p = await db.execute(select(User).where(User.id == next_id))
            pu = p.scalar_one_or_none()
            out["next_turn"] = pu.username if pu else "?"

        await db.commit()
        if room_name:
            await manager.broadcast(room_name, out)


async def _game_quiz_answer(user_id, username, game_id, answer, room_name):
    if not answer:
        return
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(ActiveGame).where(ActiveGame.id == game_id))
        game = r.scalar_one_or_none()
        if not game or game.status != "active":
            return

        new_state, result_msg, points = quiz_answer(game.state, username, answer)
        game.state = new_state
        game.updated_at = datetime.utcnow()

        out = {
            "type": "game_update", "game_type": "quiz", "game_id": game_id,
            "room": room_name, "player": username,
            "result": result_msg, "points": points,
            "scores": quiz_render_scores(new_state["scores"]),
        }

        # Auto advance after 3 seconds
        if new_state["status"] == "finished":
            game.status = "finished"
            out["message"] = f"🏆 Quiz Over!\n{quiz_render_scores(new_state['scores'])}"
            # Update scores
            for uname, score in new_state["scores"].items():
                u_r = await db.execute(select(User).where(User.username == uname))
                u = u_r.scalar_one_or_none()
                if u:
                    u.score = (u.score or 0) + score

        await db.commit()
        if room_name:
            await manager.broadcast(room_name, out)

        if new_state["status"] == "active":
            asyncio.create_task(_quiz_next(game_id, room_name, 5))


async def _quiz_next(game_id: int, room_name: str, delay: int):
    await asyncio.sleep(delay)
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(ActiveGame).where(ActiveGame.id == game_id))
        game = r.scalar_one_or_none()
        if not game or game.status != "active":
            return
        new_state, next_q = quiz_next_question(game.state)
        game.state = new_state
        await db.commit()
        if next_q and room_name:
            current = new_state["current"]
            total = len(new_state["questions"])
            await manager.broadcast(room_name, {
                "type": "game_update", "game_type": "quiz", "game_id": game_id,
                "room": room_name, "question": quiz_render_question(next_q, current, total),
            })
        elif room_name:
            await manager.broadcast(room_name, {
                "type": "game_update", "game_type": "quiz", "game_id": game_id,
                "room": room_name, "message": f"🏆 Quiz finished!\n{quiz_render_scores(new_state['scores'])}",
            })


async def _update_game_stats(db, p1_id, p2_id, game: str, winner_id):
    for pid in [p1_id, p2_id]:
        if not pid:
            continue
        r = await db.execute(select(GameStat).where(and_(GameStat.user_id == pid, GameStat.game == game)))
        stat = r.scalar_one_or_none()
        if not stat:
            stat = GameStat(user_id=pid, game=game)
            db.add(stat)
        if pid == winner_id:
            stat.wins = (stat.wins or 0) + 1
            stat.score = (stat.score or 0) + 100
        else:
            stat.losses = (stat.losses or 0) + 1
        stat.updated_at = datetime.utcnow()


async def _deliver_offline(user_id: int, db):
    result = await db.execute(select(Notification).where(and_(Notification.user_id == user_id, Notification.is_read == False)))
    notifications = result.scalars().all()
    for n in notifications:
        await manager.send(user_id, {
            "type": "notification",
            "notification_type": n.type,
            "content": json.loads(n.content),
            "timestamp": n.created_at.isoformat(),
        })
        n.is_read = True
    if notifications:
        await db.commit()
