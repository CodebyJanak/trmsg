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

## Installing on Restricted Computers (College / No Admin)

If you get **permission denied** or **websockets not found** errors on a college or shared computer, use one of these methods. No admin rights needed.

---

### ✅ Method 1 — Virtual Environment (Recommended)

Works on any computer. Zero admin rights needed.

```bash
# Create a virtual environment in your home folder
python3 -m venv ~/trmsg-env

# Activate it
source ~/trmsg-env/bin/activate        # Linux / Mac / Android
# OR on Windows:
# ~/trmsg-env/Scripts/activate

# Install freely — no permission errors
pip install websockets==12.0
pip install trmsg

# Use trmsg
trmsg config
trmsg register
trmsg chat
```

> Every time you open a new terminal, activate first:
> ```bash
> source ~/trmsg-env/bin/activate
> ```

---

### Method 2 — User Install (--user flag)

If venv doesn't work, install to your personal folder:

```bash
# Install with --user flag (no admin needed)
python3 -m pip install --user websockets==12.0
python3 -m pip install --user trmsg
```

If `trmsg` command is not found after install:

```bash
# Add user bin to PATH
export PATH="$HOME/.local/bin:$PATH"

# Make it permanent
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

---

### Method 3 — Install Dependencies Manually

If you get missing package errors, install each one manually:

```bash
python3 -m pip install --user --upgrade pip
python3 -m pip install --user websockets==12.0
python3 -m pip install --user httpx==0.27.0
python3 -m pip install --user rich==13.7.0
python3 -m pip install --user click==8.1.7
python3 -m pip install --user python-jose==3.3.0
python3 -m pip install --user pydantic==2.6.0
python3 -m pip install --user trmsg
```

---

### Common Errors & Fixes

| Error | Fix |
|-------|-----|
| `Permission denied` | Add `--user` flag or use venv |
| `trmsg: command not found` | Run `export PATH="$HOME/.local/bin:$PATH"` |
| `No module named websockets` | `pip install --user websockets==12.0` |
| `pip: command not found` | Use `python3 -m pip` instead of `pip` |
| `Python version too old` | Need Python 3.10+. Check: `python3 --version` |
| `externally-managed-environment` | Use venv (Method 1) — this is a system Python restriction |

---

### Quick Check — Is Everything Installed?

```bash
python3 -c "import websockets, httpx, rich, click; print('✓ All good!')"
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
