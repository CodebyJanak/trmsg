"""trmsg - Auth Commands"""
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from cli.config import config
from cli.network.client import APIClient, APIError
from cli.ui.theme import print_banner, print_error, print_success, print_info, console

async def register_command():
    print_banner(config.theme)
    console.print(Panel.fit("[bold bright_green]Create Account[/bold bright_green]", border_style="bright_green"))
    api = APIClient()
    try:
        username = Prompt.ask("[cyan]Username[/cyan]").strip()
        password = Prompt.ask("[cyan]Password[/cyan]", password=True)
        confirm  = Prompt.ask("[cyan]Confirm password[/cyan]", password=True)
        if password != confirm: print_error("Passwords don't match!"); return
        if len(password) < 8: print_error("Password must be 8+ characters!"); return
        email        = Prompt.ask("[cyan]Email[/cyan] [dim](optional)[/dim]", default="").strip() or None
        display_name = Prompt.ask("[cyan]Display name[/cyan]", default=username).strip()
        with console.status("[green]Creating account...[/green]"):
            result = await api.post("/api/v1/users/register", {"username":username,"password":password,"email":email,"display_name":display_name})
        config.token = result["token"]; config.username = result["username"]; config.avatar_color = result.get("avatar_color","#00ff88")
        print_success(f"Welcome to trmsg, [bold]{result['username']}[/bold]! ⚡")
        print_info("Run [bold]trmsg chat[/bold] to start!")
    except APIError as e: print_error(f"Registration failed: {e.message}")
    finally: await api.close()

async def login_command():
    print_banner(config.theme)
    if config.is_authenticated():
        print_info(f"Already logged in as [bold]{config.username}[/bold]")
        if not Confirm.ask("Login as different user?"): return
    api = APIClient()
    try:
        username = Prompt.ask("[cyan]Username[/cyan]").strip()
        password = Prompt.ask("[cyan]Password[/cyan]", password=True)
        with console.status("[green]Logging in...[/green]"):
            result = await api.post("/api/v1/users/login", {"username":username,"password":password})
        config.token = result["token"]; config.username = result["username"]
        config.avatar_color = result.get("avatar_color","#00ff88")
        if result.get("theme"): config.theme = result["theme"]
        print_success(f"Welcome back, [bold]{result.get('display_name',username)}[/bold]! ⚡")
        print_info("Run [bold]trmsg chat[/bold] to start!")
    except APIError as e: print_error(f"Login failed: {e.message}")
    finally: await api.close()

def logout_command():
    if not config.is_authenticated(): print_info("Not logged in."); return
    username = config.username; config.clear_auth()
    print_success(f"Logged out [bold]{username}[/bold]. Goodbye! 👋")

async def profile_command():
    api = APIClient()
    try:
        me = await api.get("/api/v1/users/me")
        s = await api.get(f"/api/v1/users/{me['username']}/stats")
        console.print(f"\n[bold cyan]Your Profile[/bold cyan]")
        console.print(f"  Username:     [bold]{me['username']}[/bold]")
        console.print(f"  Display name: {me.get('display_name','—')}")
        console.print(f"  Bio:          {me.get('bio','—')}")
        console.print(f"  Status:       {me.get('status','offline')}")
        console.print(f"  Role:         {me.get('role','member')}")
        console.print(f"  Score:        🏆 {s.get('score',0)} (Rank #{s.get('rank','?')})")
        console.print(f"  Messages:     {s.get('total_messages',0)}")
        console.print(f"  Theme:        {me.get('theme','cyberpunk')}")
        console.print(f"  Server:       {config.server_url}\n")
        if Confirm.ask("Edit profile?"):
            display_name = Prompt.ask("Display name", default=me.get("display_name","")).strip()
            bio = Prompt.ask("Bio", default=me.get("bio","")).strip()
            with console.status("[green]Updating...[/green]"):
                await api.patch("/api/v1/users/me", {"display_name":display_name,"bio":bio})
            print_success("Profile updated!")
    except APIError as e: print_error(f"Failed: {e.message}")
    finally: await api.close()

def configure_command():
    console.print("\n[bold cyan]trmsg Configuration[/bold cyan]\n")
    server = Prompt.ask("[cyan]Server URL[/cyan]", default=config.server_url)
    config.server_url = server.rstrip("/")
    from cli.ui.theme import THEMES
    theme = Prompt.ask("[cyan]Theme[/cyan]", default=config.theme, choices=list(THEMES.keys()))
    config.theme = theme
    dl_dir = Prompt.ask("[cyan]Download directory[/cyan]", default=str(config.download_dir))
    config.download_dir = dl_dir
    print_success("Configuration saved!")
