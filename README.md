# ⚡ trmsg

**Terminal messaging. Chat. Share files. Play games. All from your CLI.**

```bash
pip install trmsg
```

---

## Features

| Feature | Command |
|---|---|
| 💬 Real-time chat | `trmsg chat` |
| 📁 File sharing (200MB) | `/sendfile photo.jpg` |
| 👥 Friends & DMs | `/add username` |
| 🤖 AI Assistant (Gemini) | `/ai what is python?` |
| 💣 Self-destruct messages | `/burn 30 secret message` |
| 🎮 TicTacToe | `/game ttt opponent` |
| ♟️ Chess | `/game chess opponent` |
| 🧠 Quiz Battle | `/game quiz` |
| 🏆 Leaderboard | `/leaderboard` |
| 📊 Polls | `/poll "Q?" A \| B \| C` |
| 😀 Reactions | `/react 5 👍` |
| ↩️ Reply to messages | `/reply 5 good point!` |
| 🔔 Keyword alerts | `/alert homework` |
| 🌙 Do Not Disturb | `/dnd 11pm-7am` |
| 🎨 Themes | `/theme matrix` |
| 🔗 Invite links | `/invite create` |
| 📋 Message search | `/search-msg keyword` |
| 💻 Code sharing | `/code python print("hi")` |
| 📣 Announcements | `/announce Important update!` |
| 👑 Roles | Owner / Admin / VIP / Member |

---

## Quick Start

```bash
# Install
pip install trmsg

# Connect to a server
trmsg config

# Register
trmsg register

# Chat!
trmsg chat
```

---

## Self-Host Server

```bash
pip install "trmsg[server]"

# Setup
echo "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" > .env
echo "DATABASE_URL=sqlite+aiosqlite:///./trmsg.db" >> .env
echo "GEMINI_API_KEY=your-key-here" >> .env  # optional AI
mkdir uploads

# Start
trmsg-server
```

Friends connect: `trmsg config` → enter your IP → `trmsg register` → `trmsg chat`

---

## AI Commands

```bash
/ai what is async/await?
/ai summarize                    # summarize last 50 messages
/ai translate Japanese hello     # translate text
/ai explain def foo(): pass      # explain code
/ai roast janak                  # friendly roast 😈
```

Powered by **Gemini 1.5 Flash** (free). Add `GEMINI_API_KEY` to server `.env`.

---

## Game Commands

```bash
/game ttt rohan        # TicTacToe vs rohan
/game chess priya      # Chess vs priya
/game quiz             # Quiz battle (room plays together)

/move <id> 5           # TTT: pick cell 1-9
/move <id> e2e4        # Chess: algebraic notation
/answer B              # Quiz: answer A/B/C/D

/leaderboard           # Overall rankings
/leaderboard ttt       # Game-specific rankings
/mystats               # Your personal stats
```

---

## All CLI Commands

```bash
trmsg register       trmsg login         trmsg logout
trmsg chat           trmsg chat <user>   (DM someone)
trmsg friends        trmsg users         trmsg rooms
trmsg add <user>     trmsg whois <user>  trmsg stats
trmsg leaderboard    trmsg profile       trmsg config
```

---

## Themes

```bash
/theme cyberpunk    # neon green (default)
/theme matrix       # matrix falling code style
/theme ocean        # cool blue tones
/theme sunset       # warm red/yellow
/theme hacker       # deep green hacker
/theme minimal      # clean white
```

---

## Deploy to Render (Free)

1. Push to GitHub
2. Render → New Web Service → connect repo
3. Build: `pip install ".[server]"`  
4. Start: `trmsg-server`
5. Env vars: `SECRET_KEY`, `DATABASE_URL`, `GEMINI_API_KEY`

Share URL → friends install trmsg → connect → chat! 🎉

---

*Built with FastAPI · SQLAlchemy · WebSockets · Rich · Click · Gemini AI*
