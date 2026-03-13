"""trmsg - Full Chat UI with scrollable output"""
import asyncio, os, json, sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from collections import deque
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markup import escape
from rich.text import Text
from cli.config import config
from cli.network.client import APIClient, WSClient, APIError
from cli.ui.theme import (get_user_color, get_status_icon, get_role_badge,
    format_timestamp, render_content, make_avatar, format_size,
    print_error, print_success, get_theme, THEMES)

console = Console()

class Msg:
    def __init__(self, sender, content, timestamp, msg_id=0, is_self=False,
                 is_system=False, msg_type="text", reply_to=None, reactions=None,
                 avatar_color=None, display_name=None, is_edited=False,
                 file_info=None, code_language=None, burn_after=None, role=None):
        self.sender=sender; self.display_name=display_name or sender
        self.content=content; self.timestamp=timestamp; self.msg_id=msg_id
        self.is_self=is_self; self.is_system=is_system; self.msg_type=msg_type
        self.reply_to=reply_to; self.reactions=reactions or {}
        self.avatar_color=avatar_color; self.is_edited=is_edited
        self.file_info=file_info; self.code_language=code_language
        self.burn_after=burn_after; self.role=role

class ChatUI:
    MAX_MSGS = 500
    # How many rendered lines to show in the chat viewport
    CHAT_LINES = 20

    def __init__(self, username, target=None, theme="cyberpunk"):
        self.username = username
        self.target = target
        self.current_room = "general"
        self.messages = deque(maxlen=self.MAX_MSGS)
        self.notifications = deque(maxlen=10)
        self.online_users = []
        self.friends = []
        self.my_rooms = []
        self.typing_users = set()
        self.ws = None
        self.api = None
        self._running = False
        self._reply_to = None
        self._active_game = None
        self._polls = {}
        self._theme = get_theme(theme)
        self._unread = {}
        # Scroll state: None means "follow latest" (auto-scroll)
        self._scroll_offset = 0   # lines from the bottom; 0 = latest
        self._rendered_lines = [] # cache of all rendered lines

    async def run(self):
        self.api = APIClient()
        self._running = True

        if self.target:
            self.current_room = "dm_" + "_".join(sorted([self.username, self.target]))
        else:
            self.current_room = "general"
            try: await self.api.post("/api/v1/rooms", {"name":"general","description":"General chat","icon":"👋"})
            except APIError: pass
            try: await self.api.post("/api/v1/rooms/general/join")
            except APIError: pass

        await self._load_history()
        await self._refresh_sidebar()

        self.ws = WSClient(on_message=self._on_ws)
        try:
            await self.ws.connect()
        except Exception as e:
            print_error(f"Cannot connect: {e}"); return

        await self.ws.join_room(self.current_room)

        try:
            await self._loop()
        finally:
            await self.ws.disconnect()
            await self.api.close()

    async def _loop(self):
        ws_task = asyncio.create_task(self.ws.listen())
        refresh_task = asyncio.create_task(self._periodic_refresh())
        typing_task = asyncio.create_task(self._typing_cleanup())
        self._rebuild_lines()
        self._render()

        try:
            while self._running:
                line = await asyncio.get_event_loop().run_in_executor(None, self._read_input)
                if line is None:
                    break
                await self._handle_input(line.strip())
                self._rebuild_lines()
                self._render()
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            for t in [ws_task, refresh_task, typing_task]:
                t.cancel()
            console.print("\n[dim]Goodbye! ⚡[/dim]")

    def _read_input(self):
        try:
            room_label = self._room_label_plain()
            scroll_hint = ""
            if self._scroll_offset > 0:
                scroll_hint = f" [↑{self._scroll_offset} lines scrolled | PgDn=latest]"
            typing = f" {', '.join(list(self.typing_users)[:2])} typing..." if self.typing_users else ""
            reply = f" [reply to #{self._reply_to}]" if self._reply_to else ""
            prompt = f"\n{room_label}{scroll_hint}{typing}{reply} ❯ "
            sys.stdout.write(prompt)
            sys.stdout.flush()
            return input()
        except (EOFError, KeyboardInterrupt):
            return None

    async def _handle_input(self, text):
        if not text:
            return
        config.add_history(text)

        # Scroll controls (no network needed)
        if text in ("/pgup", "/up", "/u"):
            self._scroll_offset = min(self._scroll_offset + self.CHAT_LINES, max(0, len(self._rendered_lines) - self.CHAT_LINES))
            return
        if text in ("/pgdn", "/down", "/d"):
            self._scroll_offset = max(0, self._scroll_offset - self.CHAT_LINES)
            return
        if text in ("/top",):
            self._scroll_offset = max(0, len(self._rendered_lines) - self.CHAT_LINES)
            return
        if text in ("/bottom", "/latest", "/b"):
            self._scroll_offset = 0
            return

        if text.lower() in ("/quit", "/exit", "/q"):
            self._running = False
            return
        if text.startswith("/"):
            await self._handle_command(text)
        else:
            await self.ws.send_message(self.current_room, text, reply_to=self._reply_to)
            self._reply_to = None
            self.messages.append(Msg(
                sender=self.username, content=text,
                timestamp=format_timestamp(datetime.utcnow().isoformat()),
                is_self=True, avatar_color=config.avatar_color
            ))
            self._scroll_offset = 0  # auto-scroll to bottom on send
            await self.ws.typing_stop(self.current_room)

    # ── COMMANDS ──────────────────────────────────────────────────
    async def _handle_command(self, cmd):
        parts = cmd.strip().split(maxsplit=3)
        c = parts[0].lower()
        cmds = {
            "/join": self._cmd_join, "/leave": self._cmd_leave,
            "/create": self._cmd_create, "/create-room": self._cmd_create,
            "/rooms": self._cmd_rooms, "/msg": self._cmd_dm,
            "/history": self._cmd_history, "/reply": self._cmd_reply,
            "/edit": self._cmd_edit, "/delete": self._cmd_delete,
            "/react": self._cmd_react, "/unreact": self._cmd_unreact,
            "/sendfile": self._cmd_sendfile, "/sf": self._cmd_sendfile,
            "/download": self._cmd_download, "/dl": self._cmd_download,
            "/add": self._cmd_add, "/accept": self._cmd_accept,
            "/reject": self._cmd_reject, "/friends": self._cmd_friends,
            "/requests": self._cmd_requests, "/users": self._cmd_users,
            "/whois": self._cmd_whois, "/search": self._cmd_search,
            "/poll": self._cmd_poll, "/vote": self._cmd_vote,
            "/status": self._cmd_status,
            "/away": lambda p: self._set_status("away", "AFK"),
            "/busy": lambda p: self._set_status("busy", "Do not disturb"),
            "/back": lambda p: self._set_status("online", ""),
            "/theme": self._cmd_theme, "/stats": self._cmd_stats,
            "/mystats": self._cmd_mystats, "/leaderboard": self._cmd_leaderboard,
            "/alert": self._cmd_alert, "/dnd": self._cmd_dnd,
            "/game": self._cmd_game, "/move": self._cmd_move,
            "/answer": self._cmd_answer,
            "/burn": self._cmd_burn,
            "/code": self._cmd_code,
            "/invite": self._cmd_invite, "/join-invite": self._cmd_join_invite,
            "/search-msg": self._cmd_search_msg,
            "/announce": self._cmd_announce,
            "/me": self._cmd_me,
            "/clear": lambda p: self._do_clear(),
            "/help": lambda p: self._show_help(),
            "/?": lambda p: self._show_help(),
        }
        handler = cmds.get(c)
        if handler:
            await handler(parts)
        else:
            self._sys(f"[red]Unknown:[/red] {c}  —  type [bold]/help[/bold]")

    def _do_clear(self):
        self.messages.clear()
        self._rendered_lines.clear()
        self._scroll_offset = 0

    # ── ALL COMMANDS (same as before) ─────────────────────────────
    async def _cmd_join(self, p):
        if len(p) < 2: self._sys("Usage: /join <room>"); return
        name = p[1].lower()
        try:
            await self.api.post(f"/api/v1/rooms/{name}/join")
            await self.ws.join_room(name)
            self.current_room = name
            self.messages.clear()
            self._scroll_offset = 0
            await self._load_history()
            self._sys(f"[green]✓ Joined [bold]#{name}[/bold][/green]")
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_leave(self, p):
        try:
            await self.api.post(f"/api/v1/rooms/{self.current_room}/leave")
            await self.ws.leave_room(self.current_room)
            self.current_room = "general"
            self.messages.clear()
            self._scroll_offset = 0
            await self._load_history()
            self._sys("[yellow]Left — back in #general[/yellow]")
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_create(self, p):
        if len(p) < 2: self._sys("Usage: /create <name> [desc]"); return
        try:
            await self.api.post("/api/v1/rooms", {"name": p[1].lower(), "description": p[2] if len(p)>2 else ""})
            await self.ws.join_room(p[1].lower())
            self.current_room = p[1].lower()
            self._scroll_offset = 0
            self._sys(f"[green]✓ Created [bold]#{p[1]}[/bold][/green]")
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_rooms(self, p):
        try:
            r = await self.api.get("/api/v1/rooms")
            self._sys("[cyan]📢 Public Rooms:[/cyan]")
            for rm in r.get("rooms", []):
                pw = "🔒" if rm.get("has_password") else ""
                self._sys(f"  {rm.get('icon','💬')} [bold]#{rm['name']}[/bold] {pw} — {rm.get('description','')} [{rm.get('online',0)} online]")
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_dm(self, p):
        if len(p) < 3: self._sys("Usage: /msg <user> <text>"); return
        target, content = p[1], " ".join(p[2:])
        dm_room = "dm_" + "_".join(sorted([self.username, target]))
        await self.ws.join_room(dm_room)
        await self.ws.send_message(dm_room, content)
        self.current_room = dm_room
        self._scroll_offset = 0
        self._sys(f"[magenta]→ DM to {target}[/magenta]")

    async def _cmd_history(self, p):
        room = p[1].lower() if len(p) > 1 else self.current_room
        try:
            r = await self.api.get(f"/api/v1/messages/history/{room}?limit=50")
            self.messages.clear()
            self._scroll_offset = 0
            for m in r.get("messages", []):
                self.messages.append(Msg(
                    sender=m["sender"], content=m.get("content",""),
                    timestamp=format_timestamp(m["timestamp"]),
                    msg_id=m.get("id",0), is_self=(m["sender"]==self.username),
                    display_name=m.get("display_name"), avatar_color=m.get("avatar_color"),
                    reactions=m.get("reactions",{}), reply_to=m.get("reply_to"),
                    msg_type=m.get("message_type","text"), code_language=m.get("code_language")
                ))
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_reply(self, p):
        if len(p) < 3: self._sys("Usage: /reply <id> <text>"); return
        try:
            self._reply_to = int(p[1])
            content = " ".join(p[2:])
            await self.ws.send_message(self.current_room, content, reply_to=self._reply_to)
            self._reply_to = None
            self._scroll_offset = 0
        except ValueError: self._sys("[red]✗ Invalid ID[/red]")

    async def _cmd_edit(self, p):
        if len(p) < 3: self._sys("Usage: /edit <id> <text>"); return
        try:
            await self.api.patch(f"/api/v1/messages/{int(p[1])}", {"content": " ".join(p[2:])})
            self._sys("[dim]✏ Edited[/dim]")
        except (ValueError, APIError) as e: self._sys(f"[red]✗ {e}[/red]")

    async def _cmd_delete(self, p):
        if len(p) < 2: self._sys("Usage: /delete <id>"); return
        try:
            await self.api.delete(f"/api/v1/messages/{int(p[1])}")
            self._sys("[dim]🗑 Deleted[/dim]")
        except (ValueError, APIError) as e: self._sys(f"[red]✗ {e}[/red]")

    async def _cmd_react(self, p):
        if len(p) < 3: self._sys("Usage: /react <id> <emoji>"); return
        try: await self.ws.react(int(p[1]), p[2])
        except ValueError: self._sys("[red]✗ Invalid ID[/red]")

    async def _cmd_unreact(self, p):
        if len(p) < 3: self._sys("Usage: /unreact <id> <emoji>"); return
        try: await self.ws.send({"type":"unreact","message_id":int(p[1]),"emoji":p[2]})
        except ValueError: self._sys("[red]✗ Invalid ID[/red]")

    async def _cmd_sendfile(self, p):
        if len(p) < 2: self._sys("Usage: /sendfile <path> [target]"); return
        path = Path(p[1]).expanduser()
        if not path.exists(): self._sys(f"[red]✗ File not found: {p[1]}[/red]"); return
        target = p[2] if len(p) > 2 else None
        self._sys(f"[dim]📤 Uploading {path.name} ({format_size(path.stat().st_size)})...[/dim]")
        try:
            if target and not target.startswith("#"):
                result = await self.api.upload_file(path, recipient=target)
            else:
                room = (target or "#"+self.current_room).lstrip("#")
                result = await self.api.upload_file(path, room=room)
            self._sys(f"[green]✓ Uploaded! ID: {result['file_id']} | /download {result['file_id']}[/green]")
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_download(self, p):
        if len(p) < 2: self._sys("Usage: /download <id> [name]"); return
        try:
            fid = int(p[1])
            fname = p[2] if len(p) > 2 else f"file_{fid}"
            dest = config.download_dir / fname
            self._sys(f"[dim]📥 Downloading...[/dim]")
            await self.api.download_file(fid, dest)
            self._sys(f"[green]✓ Saved: {dest}[/green]")
        except (ValueError, APIError) as e: self._sys(f"[red]✗ {e}[/red]")

    async def _cmd_burn(self, p):
        if len(p) < 3: self._sys("Usage: /burn <seconds> <message>"); return
        try:
            seconds = int(p[1])
            if seconds > 300: self._sys("[red]✗ Max 300 seconds[/red]"); return
            content = " ".join(p[2:])
            await self.ws.send_message(self.current_room, f"💣 {content}", burn_after=seconds)
            self._scroll_offset = 0
            self._sys(f"[dim]💣 Self-destructs in {seconds}s[/dim]")
        except ValueError: self._sys("[red]✗ Invalid seconds[/red]")

    async def _cmd_code(self, p):
        if len(p) < 3: self._sys("Usage: /code <language> <code>"); return
        lang = p[1].lower()
        code = " ".join(p[2:])
        await self.ws.send_message(self.current_room, f"```{lang}\n{code}\n```", code_language=lang)
        self._scroll_offset = 0

    async def _cmd_add(self, p):
        if len(p) < 2: self._sys("Usage: /add <user>"); return
        try:
            await self.api.post(f"/api/v1/friends/add/{p[1]}")
            self._sys(f"[green]✓ Request sent to {p[1]}[/green]")
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_accept(self, p):
        if len(p) < 2: self._sys("Usage: /accept <user>"); return
        try:
            await self.api.post(f"/api/v1/friends/accept/{p[1]}")
            self._sys(f"[green]✅ Now friends with {p[1]}![/green]")
            await self._refresh_sidebar()
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_reject(self, p):
        if len(p) < 2: self._sys("Usage: /reject <user>"); return
        try:
            await self.api.post(f"/api/v1/friends/reject/{p[1]}")
            self._sys(f"[dim]Rejected {p[1]}[/dim]")
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_friends(self, p):
        try:
            r = await self.api.get("/api/v1/friends/list")
            friends = r.get("friends", [])
            if not friends: self._sys("[dim]No friends yet. /add <username>[/dim]"); return
            self._sys(f"[cyan]👥 Friends ({len(friends)}):[/cyan]")
            for f in friends:
                icon = get_status_icon(f.get("status","offline"))
                sm = f" — {f['status_message']}" if f.get("status_message") else ""
                self._sys(f"  {icon} [bold]{f['username']}[/bold]{sm}")
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_requests(self, p):
        try:
            r = await self.api.get("/api/v1/friends/requests")
            reqs = r.get("requests", [])
            if not reqs: self._sys("[dim]No pending requests[/dim]"); return
            self._sys("[cyan]📨 Requests:[/cyan]")
            for req in reqs:
                self._sys(f"  • [bold]{req['username']}[/bold] — /accept {req['username']} | /reject {req['username']}")
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_users(self, p):
        try:
            r = await self.api.get("/api/v1/users/online")
            self._sys(f"[green]🟢 Online ({r.get('count',0)}):[/green]")
            for u in r.get("users", []):
                badge = get_role_badge(u.get("role","member"))
                sm = f" — {u['status_message']}" if u.get("status_message") else ""
                self._sys(f"  {badge} [bold]{u['username']}[/bold]{sm}")
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_whois(self, p):
        if len(p) < 2: self._sys("Usage: /whois <user>"); return
        try:
            u = await self.api.get(f"/api/v1/users/{p[1]}")
            s = await self.api.get(f"/api/v1/users/{p[1]}/stats")
            icon = get_status_icon(u.get("status","offline"))
            badge = get_role_badge(u.get("role","member"))
            self._sys(f"[cyan]── {u['username']} {badge} ──[/cyan]")
            self._sys(f"  Name:     {u.get('display_name',u['username'])}")
            self._sys(f"  Status:   {icon} {u.get('status','offline')}")
            if u.get("status_message"): self._sys(f"  Message:  {u['status_message']}")
            if u.get("bio"): self._sys(f"  Bio:      {u['bio']}")
            self._sys(f"  Score:    🏆 {s.get('score',0)} (Rank #{s.get('rank','?')})")
            self._sys(f"  Messages: {s.get('total_messages',0)} | Files: {s.get('total_files',0)}")
            gs = s.get("game_stats",{})
            for game, stat in gs.items():
                self._sys(f"  {game.upper()}: W{stat['wins']} L{stat['losses']}")
            self._sys(f"  Joined:   {u.get('created_at','')[:10]}")
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_search(self, p):
        if len(p) < 2: self._sys("Usage: /search <query>"); return
        try:
            r = await self.api.get(f"/api/v1/users/search?q={p[1]}")
            users = r.get("users", [])
            if not users: self._sys("[dim]No users found[/dim]"); return
            for u in users:
                icon = get_status_icon("online" if u.get("is_online") else "offline")
                badge = get_role_badge(u.get("role","member"))
                self._sys(f"  {icon} {badge} [bold]{u['username']}[/bold] ({u.get('display_name','')})")
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_poll(self, p):
        if len(p) < 2: self._sys('Usage: /poll "Q?" A | B | C'); return
        raw = " ".join(p[1:])
        if "?" not in raw: self._sys("[red]Question must end with ?[/red]"); return
        question, rest = raw.split("?", 1); question += "?"
        options = [o.strip() for o in rest.split("|") if o.strip()]
        if len(options) < 2: self._sys("[red]Need 2+ options separated by |[/red]"); return
        try:
            r = await self.api.post("/api/v1/polls", {"room": self.current_room, "question": question, "options": options})
            self._sys(f"[green]✓ Poll created! Vote: /vote {r['poll_id']} <number>[/green]")
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_vote(self, p):
        if len(p) < 3: self._sys("Usage: /vote <poll_id> <number>"); return
        try:
            await self.ws.vote_poll(int(p[1]), int(p[2])-1)
            self._sys("[green]✓ Voted![/green]")
        except (ValueError, APIError) as e: self._sys(f"[red]✗ {e}[/red]")

    async def _cmd_status(self, p):
        if len(p) < 2: self._sys("Usage: /status <online|away|busy|invisible> [msg]"); return
        await self._set_status(p[1], " ".join(p[2:]) if len(p) > 2 else "")

    async def _set_status(self, status, msg=""):
        try:
            await self.api.post("/api/v1/users/status", {"status": status, "status_message": msg})
            icon = get_status_icon(status)
            self._sys(f"{icon} Status: [bold]{status}[/bold]{' — '+msg if msg else ''}")
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_theme(self, p):
        if len(p) < 2:
            self._sys(f"[cyan]Themes:[/cyan] {', '.join(THEMES.keys())}"); return
        name = p[1].lower()
        if name not in THEMES:
            self._sys(f"[red]✗ Choose: {', '.join(THEMES.keys())}[/red]"); return
        self._theme = get_theme(name)
        config.theme = name
        self._sys(f"[green]✓ Theme: [bold]{name}[/bold][/green]")

    async def _cmd_stats(self, p):
        try:
            s = await self.api.get("/api/v1/stats")
            self._sys("[cyan]── Server Stats ──[/cyan]")
            self._sys(f"  👥 Users: {s.get('users',0)}  🟢 Online: {s.get('online_now',0)}")
            self._sys(f"  💬 Rooms: {s.get('rooms',0)}  📨 Messages: {s.get('messages',0)}")
            self._sys(f"  📎 Files: {s.get('files',0)}  🎮 Games: {s.get('games_played',0)}")
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_mystats(self, p):
        try:
            s = await self.api.get(f"/api/v1/users/{self.username}/stats")
            self._sys("[cyan]── Your Stats ──[/cyan]")
            self._sys(f"  🏆 Score: {s.get('score',0)}  Rank: #{s.get('rank','?')}")
            self._sys(f"  💬 Messages: {s.get('total_messages',0)}  📎 Files: {s.get('total_files',0)}")
            gs = s.get("game_stats",{})
            for game, stat in gs.items():
                self._sys(f"  {game.upper()}: W{stat['wins']} L{stat['losses']} Score:{stat['score']}")
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_leaderboard(self, p):
        game = p[1].lower() if len(p) > 1 else None
        try:
            url = "/api/v1/games/leaderboard" + (f"?game={game}" if game else "")
            r = await self.api.get(url)
            self._sys("[cyan]🏆 Leaderboard:[/cyan]")
            medals = ["🥇","🥈","🥉"]
            for u in r.get("overall", [])[:10]:
                medal = medals[u["rank"]-1] if u["rank"] <= 3 else f"#{u['rank']}"
                online = "[green]●[/green]" if u.get("is_online") else "[dim]○[/dim]"
                self._sys(f"  {medal} {online} [bold]{u['username']}[/bold] — {u['score']} pts")
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_alert(self, p):
        if len(p) < 2: self._sys("Usage: /alert <keyword>  or  /alert remove <keyword>"); return
        if p[1].lower() == "remove" and len(p) > 2:
            try:
                await self.api.delete(f"/api/v1/users/alert/{p[2]}")
                self._sys(f"[dim]Alert removed: '{p[2]}'[/dim]")
            except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")
        else:
            try:
                r = await self.api.post("/api/v1/users/alert", {"keyword": p[1]})
                self._sys(f"[green]✓ Alert set for '{p[1]}'[/green]")
            except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_dnd(self, p):
        if len(p) >= 2 and p[1].lower() == "off":
            try:
                await self.api.post("/api/v1/users/dnd", {"enabled": False})
                self._sys("[green]✓ DND off[/green]")
            except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")
        elif len(p) >= 2:
            try:
                times = p[1].split("-")
                start = times[0] if times else None
                end = times[1] if len(times) > 1 else None
                await self.api.post("/api/v1/users/dnd", {"enabled": True, "start": start, "end": end})
                self._sys(f"[green]✓ DND: {start} to {end}[/green]")
            except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")
        else:
            self._sys("Usage: /dnd 11pm-7am  |  /dnd off")

    async def _cmd_game(self, p):
        if len(p) < 2: self._sys("Usage: /game <ttt|chess|quiz> [opponent]"); return
        try:
            r = await self.api.post("/api/v1/games/start", {"game_type": p[1].lower(), "opponent": p[2] if len(p)>2 else None, "room": self.current_room, "num_questions": 5})
            self._active_game = r.get("game_id")
            self._scroll_offset = 0
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_move(self, p):
        if len(p) < 3: self._sys("Usage: /move <game_id> <position>"); return
        try:
            game_id = int(p[1]); move = p[2]
            if move.isdigit():
                await self.ws.game_action(action="move_ttt", game_id=game_id, position=int(move), room=self.current_room)
            else:
                await self.ws.game_action(action="move_chess", game_id=game_id, move=move, room=self.current_room)
            self._scroll_offset = 0
        except ValueError: self._sys("[red]✗ Invalid game ID[/red]")

    async def _cmd_answer(self, p):
        if len(p) < 2: self._sys("Usage: /answer <A|B|C|D>"); return
        if not self._active_game: self._sys("[red]✗ No active quiz[/red]"); return
        await self.ws.game_action(action="quiz_answer", game_id=self._active_game, answer=p[1].upper(), room=self.current_room)
        self._scroll_offset = 0

    async def _cmd_invite(self, p):
        try:
            max_uses = int(p[1]) if len(p) > 1 and p[1].isdigit() else None
            r = await self.api.post(f"/api/v1/rooms/{self.current_room}/invite", {"max_uses": max_uses})
            self._sys(f"[green]✓ Invite code: [bold bright_cyan]{r['code']}[/bold bright_cyan][/green]")
            self._sys(f"  Share: /join-invite {r['code']}")
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_join_invite(self, p):
        if len(p) < 2: self._sys("Usage: /join-invite <code>"); return
        try:
            r = await self.api.post(f"/api/v1/invite/use/{p[1]}")
            room = r.get("room","")
            await self.ws.join_room(room)
            self.current_room = room
            self.messages.clear()
            self._scroll_offset = 0
            await self._load_history()
            self._sys(f"[green]✓ {r.get('message','Joined!')}[/green]")
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_search_msg(self, p):
        if len(p) < 2: self._sys("Usage: /search-msg <keyword>"); return
        try:
            r = await self.api.get(f"/api/v1/messages/search/{self.current_room}?q={p[1]}")
            results = r.get("results", [])
            if not results: self._sys(f"[dim]No messages found[/dim]"); return
            self._sys(f"[cyan]🔍 Found {r.get('count',0)} messages:[/cyan]")
            for m in results:
                self._sys(f"  [dim]#{m['id']}[/dim] [bold]{m['sender']}[/bold]: {escape(m['content'][:80])}")
        except APIError as e: self._sys(f"[red]✗ {e.message}[/red]")

    async def _cmd_announce(self, p):
        if len(p) < 2: self._sys("Usage: /announce <message>"); return
        await self.ws.send_message(self.current_room, "📢 **ANNOUNCEMENT** 📢\n" + " ".join(p[1:]))
        self._scroll_offset = 0

    async def _cmd_me(self, p):
        action = " ".join(p[1:]) if len(p) > 1 else "is here"
        await self.ws.send_message(self.current_room, f"_{self.username} {action}_")
        self._scroll_offset = 0

    def _show_help(self):
        lines = [
            "[bold cyan]── trmsg Commands ──[/bold cyan]",
            "",
            "[bold]📜 Scroll[/bold]",
            "  /pgup  or  /u      Scroll up",
            "  /pgdn  or  /d      Scroll down",
            "  /top               Jump to oldest messages",
            "  /bottom or /b      Jump to latest messages",
            "",
            "[bold]Navigation[/bold]",
            "  /join <room>   /leave   /create <n>   /rooms   /join-invite <code>",
            "  /msg <user> <text>   (quick DM)",
            "",
            "[bold]Messages[/bold]",
            "  /reply <id> <text>    /edit <id> <t>    /delete <id>",
            "  /react <id> <emoji>   /burn <sec> <t>   /code <lang> <code>",
            "  /search-msg <kw>      /announce <text>  /me <action>",
            "",
            "[bold]Files[/bold]",
            "  /sendfile <path> [target]    /download <id> [name]",
            "",
            "[bold]Friends[/bold]",
            "  /add   /accept   /reject   /friends   /requests   /whois   /search",
            "",
            "[bold]Polls[/bold]",
            '  /poll "Q?" A | B | C     /vote <poll_id> <n>',
            "",
            "[bold]Games[/bold]",
            "  /game ttt [opp]      /game chess [opp]     /game quiz",
            "  /move <gid> <pos>    /answer <A-D>         /leaderboard   /mystats",
            "",
            "[bold]AI[/bold]",
            "  /ai <question>    /ai summarize    /ai translate <lang> <text>",
            "  /ai explain <code>    /ai roast [user]",
            "",
            "[bold]Other[/bold]",
            "  /status <online|away|busy|invisible>   /away  /busy  /back",
            "  /dnd 11pm-7am   /alert <kw>   /theme <name>   /stats   /clear   /quit",
        ]
        for line in lines:
            self._sys(line)

    # ── WEBSOCKET ─────────────────────────────────────────────────
    async def _on_ws(self, msg):
        t = msg.get("type")
        was_at_bottom = self._scroll_offset == 0

        if t == "message":
            if msg.get("sender") != self.username:
                self.messages.append(Msg(
                    sender=msg["sender"], content=msg.get("content",""),
                    timestamp=format_timestamp(msg.get("timestamp","")),
                    msg_id=msg.get("id",0), msg_type=msg.get("message_type","text"),
                    reply_to=msg.get("reply_to"), avatar_color=msg.get("avatar_color"),
                    file_info=msg.get("file"), code_language=msg.get("code_language"),
                    burn_after=msg.get("burn_after"),
                ))
                self._notify(f"💬 {msg['sender']}: {msg.get('content','')[:40]}")
                if was_at_bottom:
                    self._scroll_offset = 0

        elif t == "ai_response":
            self.messages.append(Msg(
                sender="TRM-AI", content=f"🤖 {msg.get('response','')}",
                timestamp=format_timestamp(msg.get("timestamp","")), is_system=True
            ))
            if was_at_bottom: self._scroll_offset = 0

        elif t == "poll":
            self._polls[msg["poll_id"]] = msg
            self.messages.append(Msg(
                sender=msg["sender"],
                content=f"📊 {msg['question']}\n" + "\n".join(f"  {i+1}. {o}" for i,o in enumerate(msg.get("options",[]))) + f"\n  Vote: /vote {msg['poll_id']} <number>",
                timestamp=format_timestamp(msg.get("timestamp","")),
                msg_id=msg.get("message_id",0), msg_type="poll"
            ))
            if was_at_bottom: self._scroll_offset = 0

        elif t == "system":
            self.messages.append(Msg(sender="system", content=msg.get("content",""), timestamp=format_timestamp(msg.get("timestamp","")), is_system=True))
            if was_at_bottom: self._scroll_offset = 0

        elif t == "game_started":
            self.messages.append(Msg(sender="system", content=msg.get("intro","🎮 Game started!"), timestamp=format_timestamp(msg.get("timestamp","")), is_system=True))
            self._active_game = msg.get("game_id")
            self._notify(f"🎮 {msg.get('starter')} started {msg.get('game_type','game')}!")
            if was_at_bottom: self._scroll_offset = 0

        elif t == "game_update":
            parts = []
            if msg.get("board"): parts.append(msg["board"])
            if msg.get("question"): parts.append(msg["question"])
            if msg.get("result"): parts.append(msg["result"])
            if msg.get("scores"): parts.append(msg["scores"])
            if msg.get("message"): parts.append(msg["message"])
            if msg.get("next_turn"): parts.append(f"Next turn: {msg['next_turn']}")
            if parts:
                self.messages.append(Msg(sender="🎮 Game", content="\n".join(parts), timestamp=format_timestamp(datetime.utcnow().isoformat()), is_system=True))
                if was_at_bottom: self._scroll_offset = 0

        elif t == "game_invite":
            self._notify(f"🎮 {msg.get('from')} challenged you to {msg.get('game_type')}!")
            self._sys(f"[yellow]🎮 Challenge from [bold]{msg.get('from')}[/bold]: /game {msg.get('game_type')} (game_id: {msg.get('game_id')})[/yellow]")
            self._active_game = msg.get("game_id")

        elif t == "message_burned":
            mid = msg.get("message_id")
            for m in self.messages:
                if m.msg_id == mid: m.content = "💥 [self-destructed]"; m.is_system = True; break

        elif t == "typing":
            uname = msg.get("username")
            if msg.get("is_typing"): self.typing_users.add(uname)
            else: self.typing_users.discard(uname)

        elif t == "presence":
            uname = msg.get("username"); status = msg.get("status","offline")
            if status == "online": self._notify(f"🟢 {uname} online")
            elif status == "offline": self._notify(f"⚫ {uname} offline")
            await self._refresh_online()

        elif t == "reaction":
            mid = msg.get("message_id"); emoji = msg.get("emoji"); action = msg.get("action","add")
            for m in self.messages:
                if m.msg_id == mid:
                    if action == "add": m.reactions[emoji] = m.reactions.get(emoji, 0) + 1
                    elif emoji in m.reactions:
                        m.reactions[emoji] = max(0, m.reactions[emoji]-1)
                        if not m.reactions[emoji]: del m.reactions[emoji]
                    break

        elif t == "message_deleted":
            mid = msg.get("message_id")
            for m in self.messages:
                if m.msg_id == mid: m.content = "[deleted]"; m.is_system = True; break

        elif t == "message_edited":
            mid = msg.get("message_id")
            for m in self.messages:
                if m.msg_id == mid: m.content = msg.get("content", m.content); m.is_edited = True; break

        elif t == "friend_request":
            self._notify(f"👥 Request from {msg.get('from')}")
            self._sys(f"[yellow]👥 Friend request from [bold]{msg.get('from')}[/bold] — /accept {msg.get('from')}[/yellow]")

        elif t == "friend_accepted":
            self._notify(f"✅ {msg.get('by')} accepted!")
            self._sys(f"[green]✅ [bold]{msg.get('by')}[/bold] is now your friend![/green]")
            await self._refresh_sidebar()

        elif t == "notification":
            content = msg.get("content", {})
            ntype = msg.get("notification_type","")
            if ntype == "keyword_alert":
                kw = content.get("keyword",""); sender = content.get("sender","?")
                self._notify(f"🔔 '{kw}' mentioned by {sender}")
                self._sys(f"[bright_yellow]🔔 '{kw}' mentioned by {sender} in #{content.get('room','')}[/bright_yellow]")

        self._rebuild_lines()
        self._render()

    # ── RENDER ────────────────────────────────────────────────────
    def _rebuild_lines(self):
        """Convert all messages to a flat list of rendered strings."""
        lines = []
        prev_sender = None
        for msg in list(self.messages):
            if msg.is_system:
                if "TRM-AI" in msg.sender:
                    lines.append("")
                    lines.append(f"  \033[1;32m🤖 TRM-AI\033[0m  \033[2m{msg.timestamp}\033[0m")
                    for subline in msg.content.split("\n"):
                        lines.append(f"  {subline}")
                else:
                    lines.append(f"\033[2;36m  ─ {msg.content}\033[0m")
                prev_sender = None
                continue

            show_header = msg.sender != prev_sender
            prev_sender = msg.sender

            if show_header:
                lines.append("")
                name_part = f"  {msg.display_name}  {msg.timestamp}"
                if msg.is_self:
                    lines.append(f"\033[1;97m{name_part}\033[0m")
                else:
                    lines.append(f"\033[1;96m{name_part}\033[0m")

            if msg.reply_to:
                rp = (msg.reply_to.get("content") or "")[:60]
                rn = msg.reply_to.get("sender","?")
                lines.append(f"\033[2m  ╭ ↩ {rn}: {rp}\033[0m")

            if msg.msg_type in ("file","image"):
                fi = msg.file_info or {}
                lines.append(f"  📎 {fi.get('filename', msg.content)}")
                if fi.get("id"): lines.append(f"\033[2m  /download {fi['id']}\033[0m")
            elif msg.msg_type == "poll":
                for subline in msg.content.split("\n"):
                    lines.append(f"  {subline}")
            else:
                for subline in msg.content.split("\n"):
                    lines.append(f"  {subline}")

            if msg.reactions:
                lines.append("  " + "  ".join(f"{e}×{c}" for e,c in msg.reactions.items()))

        self._rendered_lines = lines

    def _render(self):
        os.system("clear" if os.name != "nt" else "cls")
        p = self._theme.get("primary","bright_green")
        a = self._theme.get("accent","cyan")
        b = self._theme.get("border","bright_green")
        term_width = os.get_terminal_size().columns if hasattr(os, 'get_terminal_size') else 80
        term_height = os.get_terminal_size().lines if hasattr(os, 'get_terminal_size') else 24

        # Header
        console.print(Panel(
            f"[bold {p}]⚡ trmsg[/bold {p}]  [{a}]{self._room_label()}[/{a}]  [dim]{self.username}[/dim]  [dim]{len(self.online_users)} online[/dim]",
            border_style=b, padding=(0,1)
        ))

        # Notifications
        if self.notifications:
            recent = list(self.notifications)[-1:]
            for n in recent:
                console.print(f" [dim]{n['time']}[/dim] {n['text']}")

        # Chat area — scrollable
        chat_height = term_height - 7  # header + notif + footer + input
        all_lines = self._rendered_lines
        total = len(all_lines)

        if total <= chat_height:
            # All messages fit — show all
            visible = all_lines
            scroll_info = ""
        else:
            # Slice based on scroll offset from bottom
            end = total - self._scroll_offset
            start = max(0, end - chat_height)
            visible = all_lines[start:end]
            if self._scroll_offset > 0:
                above = total - end
                scroll_info = f"[dim]  ↑ {above} more messages above — /pgup to scroll, /bottom to jump to latest[/dim]"
            else:
                scroll_info = ""

        # Print visible lines
        for line in visible:
            try:
                console.print(line, highlight=False, markup=True)
            except Exception:
                console.print(escape(line), highlight=False)

        # Pad remaining space
        lines_shown = len(visible)
        for _ in range(max(0, chat_height - lines_shown)):
            console.print("")

        if scroll_info:
            console.print(scroll_info)

        # Sidebar (online + rooms) on same line as footer
        online_names = [u.get("username","?") for u in self.online_users[:5]]
        online_str = "  ".join(f"[green]●[/green] {n}" for n in online_names)
        rooms_str = "  ".join(f"[cyan]#{r.get('name','?')}[/cyan]" for r in self.my_rooms[:4])

        # Footer
        hints = "/pgup↑  /pgdn↓  /b=latest  /help  /quit"
        console.print(Panel(
            f"[dim]{hints}[/dim]   {online_str}",
            border_style="bright_black", padding=(0,1)
        ))

    def _room_label(self):
        if self.current_room.startswith("dm_"):
            parts = self.current_room[3:].split("_")
            partner = next((p for p in parts if p != self.username), parts[0])
            return f"@{partner}"
        return f"#{self.current_room}"

    def _room_label_plain(self):
        return self._room_label()

    def _sys(self, text):
        self.messages.append(Msg(
            sender="system", content=text,
            timestamp=datetime.now().strftime("%H:%M"), is_system=True
        ))

    def _notify(self, text):
        self.notifications.append({"text": text, "time": datetime.now().strftime("%H:%M")})

    async def _load_history(self):
        try:
            r = await self.api.get(f"/api/v1/messages/history/{self.current_room}?limit=100")
            for m in r.get("messages", []):
                self.messages.append(Msg(
                    sender=m["sender"], content=m.get("content",""),
                    timestamp=format_timestamp(m["timestamp"]),
                    msg_id=m.get("id",0), is_self=(m["sender"]==self.username),
                    display_name=m.get("display_name"), avatar_color=m.get("avatar_color"),
                    reactions=m.get("reactions",{}), reply_to=m.get("reply_to"),
                    msg_type=m.get("message_type","text"), code_language=m.get("code_language")
                ))
        except APIError:
            pass

    async def _refresh_sidebar(self):
        await self._refresh_friends(); await self._refresh_rooms(); await self._refresh_online()

    async def _refresh_friends(self):
        try: r = await self.api.get("/api/v1/friends/list"); self.friends = r.get("friends",[])
        except APIError: pass

    async def _refresh_rooms(self):
        try: r = await self.api.get("/api/v1/rooms/my"); self.my_rooms = r.get("rooms",[])
        except APIError: pass

    async def _refresh_online(self):
        try: r = await self.api.get("/api/v1/users/online"); self.online_users = r.get("users",[])
        except APIError: pass

    async def _periodic_refresh(self):
        while self._running:
            await asyncio.sleep(30)
            await self._refresh_sidebar()
            self._rebuild_lines()
            self._render()

    async def _typing_cleanup(self):
        while self._running:
            await asyncio.sleep(6)
            self.typing_users.clear()
