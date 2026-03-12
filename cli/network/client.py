"""trmsg - Network Client"""
import json, httpx, websockets
from pathlib import Path
from typing import Optional, Callable
from cli.config import config

class APIError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        self.message = message; self.status_code = status_code; super().__init__(message)

class APIClient:
    def __init__(self): self._client = None

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if config.token: h["Authorization"] = f"Bearer {config.token}"
        return h

    async def _c(self):
        if not self._client or self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=config.server_url, timeout=30.0)
        return self._client

    def _handle(self, r):
        if r.status_code >= 400:
            try: detail = r.json().get("detail", r.text)
            except: detail = r.text
            raise APIError(str(detail), r.status_code)
        try: return r.json()
        except: return {"message": r.text}

    async def get(self, path): c = await self._c(); return self._handle(await c.get(path, headers=self._headers()))
    async def post(self, path, data=None): c = await self._c(); return self._handle(await c.post(path, json=data or {}, headers=self._headers()))
    async def patch(self, path, data=None): c = await self._c(); return self._handle(await c.patch(path, json=data or {}, headers=self._headers()))
    async def delete(self, path): c = await self._c(); return self._handle(await c.delete(path, headers=self._headers()))

    async def upload_file(self, file_path: Path, room=None, recipient=None):
        c = await self._c()
        params = {}
        if room: params["room"] = room
        if recipient: params["recipient"] = recipient
        with open(file_path, "rb") as f:
            files = {"file": (file_path.name, f, "application/octet-stream")}
            r = await c.post("/api/v1/files/upload", files=files, params=params, headers={"Authorization": f"Bearer {config.token}"})
        return self._handle(r)

    async def download_file(self, file_id: int, save_path: Path, progress_cb=None):
        c = await self._c()
        async with c.stream("GET", f"/api/v1/files/{file_id}/download", headers=self._headers()) as r:
            if r.status_code != 200: raise APIError(f"Download failed: {r.status_code}")
            total = int(r.headers.get("content-length", 0))
            done = 0
            with open(save_path, "wb") as f:
                async for chunk in r.aiter_bytes(65536):
                    f.write(chunk); done += len(chunk)
                    if progress_cb and total: progress_cb(done, total)
        return save_path

    async def close(self):
        if self._client and not self._client.is_closed: await self._client.aclose()

class WSClient:
    def __init__(self, on_message: Callable): self.on_message = on_message; self._ws = None

    async def connect(self):
        if not config.token: raise APIError("Not authenticated")
        url = f"{config.ws_url}/ws?token={config.token}"
        self._ws = await websockets.connect(url, ping_interval=30, ping_timeout=10, additional_headers={"Origin": config.server_url})

    async def listen(self):
        try:
            async for raw in self._ws:
                try: await self.on_message(json.loads(raw))
                except json.JSONDecodeError: pass
        except websockets.ConnectionClosed: pass

    async def send(self, data: dict):
        if self._ws:
            try: await self._ws.send(json.dumps(data, default=str))
            except: pass

    async def disconnect(self):
        if self._ws: await self._ws.close()

    async def send_message(self, room, content, reply_to=None, burn_after=None, code_language=None):
        await self.send({"type": "chat", "room": room, "content": content, "reply_to": reply_to, "burn_after": burn_after, "code_language": code_language})

    async def join_room(self, room): await self.send({"type": "join_room", "room": room})
    async def leave_room(self, room): await self.send({"type": "leave_room", "room": room})
    async def typing_start(self, room): await self.send({"type": "typing_start", "room": room})
    async def typing_stop(self, room): await self.send({"type": "typing_stop", "room": room})
    async def react(self, message_id, emoji): await self.send({"type": "react", "message_id": message_id, "emoji": emoji})
    async def vote_poll(self, poll_id, option_index): await self.send({"type": "poll_vote", "poll_id": poll_id, "option_index": option_index})
    async def game_action(self, **kwargs): await self.send({"type": "game_action", **kwargs})
