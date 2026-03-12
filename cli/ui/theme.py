"""trmsg - UI Theme"""
import re
from datetime import datetime
from rich.console import Console

console = Console()

STATUS_ICONS = {"online":"[bold green]●[/bold green]","away":"[bold yellow]●[/bold yellow]","busy":"[bold red]●[/bold red]","invisible":"[dim]●[/dim]","offline":"[dim]○[/dim]"}
USER_COLORS = ["bright_cyan","bright_magenta","bright_yellow","bright_blue","bright_red","cyan","magenta","yellow","green","bright_green"]

ROLE_BADGES = {"owner":"[bold yellow]👑[/bold yellow]","admin":"[bold cyan]🛡[/bold cyan]","vip":"[bold magenta]⭐[/bold magenta]","member":"","bot":"[dim]🤖[/dim]"}

THEMES = {
    "cyberpunk": {"primary":"bright_green","accent":"bright_cyan","bg":"black","border":"bright_green"},
    "ocean":     {"primary":"bright_blue","accent":"cyan","bg":"black","border":"blue"},
    "matrix":    {"primary":"green","accent":"bright_green","bg":"black","border":"green"},
    "sunset":    {"primary":"bright_red","accent":"bright_yellow","bg":"black","border":"red"},
    "minimal":   {"primary":"white","accent":"bright_white","bg":"black","border":"white"},
    "hacker":    {"primary":"bright_green","accent":"green","bg":"black","border":"dim green"},
}

BANNER = r"""
  __                              
 / /_ ______ _  ___ ___ _  ___ _ 
/ __// __/  ' \(_-</ _ `/ / _ `/  
\__//_/ /_/_/_/___/\_, /  \_, /   
                  /___/  /___/  v1
"""

def get_theme(name="cyberpunk"):
    return THEMES.get(name, THEMES["cyberpunk"])

def print_banner(theme="cyberpunk"):
    t = get_theme(theme)
    console.print(f"[bold {t['primary']}]{BANNER}[/bold {t['primary']}]")
    console.print(f"[dim]  Terminal messaging. Chat. Share. Play. No browser needed.[/dim]\n")

def print_error(msg): console.print(f"[bold red]✗[/bold red] {msg}")
def print_success(msg): console.print(f"[bold bright_green]✓[/bold bright_green] {msg}")
def print_info(msg): console.print(f"[dim cyan]ℹ[/dim cyan] {msg}")
def print_warning(msg): console.print(f"[yellow]⚠[/yellow] {msg}")

def get_user_color(username):
    return USER_COLORS[sum(ord(c) for c in username) % len(USER_COLORS)]

def get_status_icon(status):
    return STATUS_ICONS.get(status, STATUS_ICONS["offline"])

def get_role_badge(role):
    return ROLE_BADGES.get(role, "")

def format_timestamp(ts):
    try:
        dt = datetime.fromisoformat(ts.replace("Z","+00:00"))
        now = datetime.utcnow()
        diff = (now - dt.replace(tzinfo=None)).total_seconds()
        if diff < 60: return "just now"
        elif diff < 3600: return f"{int(diff/60)}m ago"
        elif dt.date() == now.date(): return dt.strftime("%H:%M")
        else: return dt.strftime("%b %d %H:%M")
    except: return ts[:16] if ts else ""

def format_size(size):
    for unit in ["B","KB","MB","GB"]:
        if size < 1024: return f"{size:.1f}{unit}"
        size //= 1024
    return f"{size:.1f}GB"

def render_content(text):
    text = re.sub(r'```(\w+)?\n?(.*?)```', lambda m: f"[bold bright_yellow on black] {m.group(2).strip()} [/bold bright_yellow on black]", text, flags=re.DOTALL)
    text = re.sub(r'`([^`]+)`', r'[bold bright_yellow on black] \1 [/bold bright_yellow on black]', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'[bold]\1[/bold]', text)
    text = re.sub(r'\*(.+?)\*', r'[italic]\1[/italic]', text)
    text = re.sub(r'~~(.+?)~~', r'[strike]\1[/strike]', text)
    text = re.sub(r'(https?://\S+)', r'[underline cyan]\1[/underline cyan]', text)
    text = re.sub(r'@(\w+)', r'[bold bright_yellow]@\1[/bold bright_yellow]', text)
    text = re.sub(r'#(\w+)', r'[bold cyan]#\1[/bold cyan]', text)
    return text

def make_avatar(username, color=None):
    letter = username[0].upper() if username else "?"
    c = color or get_user_color(username)
    return f"[bold {c}]{letter}[/bold {c}]"

def progress_bar(current, total, width=20):
    if total == 0: return "[" + "─"*width + "]"
    filled = int(width * current / total)
    bar = "█"*filled + "░"*(width-filled)
    return f"[green]{bar}[/green] {int(100*current/total)}%"
