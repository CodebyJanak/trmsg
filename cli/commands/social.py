"""trmsg - Social Commands"""
from rich.table import Table
from cli.network.client import APIClient, APIError
from cli.ui.theme import print_error, print_success, print_info, get_status_icon, get_role_badge, format_timestamp, console

async def cmd_add(username):
    api = APIClient()
    try:
        with console.status(f"[green]Sending to {username}...[/green]"):
            await api.post(f"/api/v1/friends/add/{username}")
        print_success(f"Friend request sent to [bold]{username}[/bold] 📨")
    except APIError as e: print_error(f"Failed: {e.message}")
    finally: await api.close()

async def cmd_friends():
    api = APIClient()
    try:
        with console.status("[green]Loading...[/green]"): r = await api.get("/api/v1/friends/list")
        friends = r.get("friends",[])
        if not friends: print_info("No friends yet. Use [bold]trmsg add <username>[/bold]"); return
        t = Table(title="👥 Friends",border_style="bright_black",header_style="bold cyan")
        t.add_column("",width=3); t.add_column("Username",style="bright_cyan"); t.add_column("Display Name"); t.add_column("Status"); t.add_column("Last Seen",style="dim")
        for f in friends:
            icon = get_status_icon(f.get("status","offline"))
            t.add_row(icon, f["username"], f.get("display_name",""), f.get("status_message","") or "", format_timestamp(f.get("last_seen","")) if f.get("last_seen") else "—")
        console.print(t)
    except APIError as e: print_error(f"Failed: {e.message}")
    finally: await api.close()

async def cmd_users():
    api = APIClient()
    try:
        with console.status("[green]Fetching...[/green]"): r = await api.get("/api/v1/users/online")
        users = r.get("users",[]); count = r.get("count",0)
        if not users: print_info("No users online."); return
        t = Table(title=f"🟢 Online ({count})",border_style="green",header_style="bold green")
        t.add_column("",width=3); t.add_column("",width=3); t.add_column("Username",style="bright_cyan"); t.add_column("Display Name"); t.add_column("Score",justify="right",style="yellow")
        for u in users:
            icon = get_status_icon(u.get("status","online"))
            badge = get_role_badge(u.get("role","member"))
            t.add_row(icon, badge, u["username"], u.get("display_name",""), str(u.get("score",0)))
        console.print(t)
    except APIError as e: print_error(f"Failed: {e.message}")
    finally: await api.close()

async def cmd_leaderboard():
    api = APIClient()
    try:
        with console.status("[green]Loading...[/green]"): r = await api.get("/api/v1/games/leaderboard")
        t = Table(title="🏆 Leaderboard",border_style="yellow",header_style="bold yellow")
        t.add_column("Rank",width=5); t.add_column("",width=3); t.add_column("Username",style="bright_cyan"); t.add_column("Score",justify="right",style="bright_yellow"); t.add_column("Status",width=3)
        medals = ["🥇","🥈","🥉"]
        for u in r.get("overall",[]):
            rank = medals[u["rank"]-1] if u["rank"]<=3 else f"#{u['rank']}"
            status = "[green]●[/green]" if u.get("is_online") else "[dim]○[/dim]"
            t.add_row(rank, "", u["username"], str(u["score"]), status)
        console.print(t)
    except APIError as e: print_error(f"Failed: {e.message}")
    finally: await api.close()

async def cmd_stats():
    api = APIClient()
    try:
        with console.status("[green]Fetching...[/green]"): s = await api.get("/api/v1/stats")
        console.print("\n[bold cyan]── trmsg Server Stats ──[/bold cyan]")
        console.print(f"  👥 Users:    [bold]{s.get('users',0)}[/bold]")
        console.print(f"  🟢 Online:   [bold bright_green]{s.get('online_now',0)}[/bold bright_green]")
        console.print(f"  💬 Rooms:    [bold]{s.get('rooms',0)}[/bold]")
        console.print(f"  📨 Messages: [bold]{s.get('messages',0)}[/bold]")
        console.print(f"  📎 Files:    [bold]{s.get('files',0)}[/bold]")
        console.print(f"  🎮 Games:    [bold]{s.get('games_played',0)}[/bold]\n")
    except APIError as e: print_error(f"Failed: {e.message}")
    finally: await api.close()

async def cmd_whois(username):
    api = APIClient()
    try:
        with console.status(f"[green]Looking up {username}...[/green]"):
            u = await api.get(f"/api/v1/users/{username}")
            s = await api.get(f"/api/v1/users/{username}/stats")
        icon = get_status_icon(u.get("status","offline"))
        badge = get_role_badge(u.get("role","member"))
        console.print(f"\n[bold cyan]── {u['username']} {badge} ──[/bold cyan]")
        console.print(f"  Display:  {u.get('display_name',u['username'])}")
        console.print(f"  Status:   {icon} {u.get('status','offline')}")
        if u.get("status_message"): console.print(f"  Message:  {u['status_message']}")
        if u.get("bio"): console.print(f"  Bio:      {u['bio']}")
        console.print(f"  Score:    🏆 {s.get('score',0)} (Rank #{s.get('rank','?')})")
        console.print(f"  Messages: {s.get('total_messages',0)} | Files: {s.get('total_files',0)}")
        gs = s.get("game_stats",{})
        if gs:
            for game, stat in gs.items():
                console.print(f"  {game.upper()}:   W:{stat['wins']} L:{stat['losses']} Score:{stat['score']}")
        console.print(f"  Joined:   {u.get('created_at','')[:10]}\n")
    except APIError as e: print_error(f"Failed: {e.message}")
    finally: await api.close()

async def cmd_rooms():
    api = APIClient()
    try:
        with console.status("[green]Loading...[/green]"): r = await api.get("/api/v1/rooms")
        rooms = r.get("rooms",[])
        if not rooms: print_info("No public rooms."); return
        t = Table(title="📢 Public Rooms",border_style="bright_black",header_style="bold cyan")
        t.add_column("Icon",width=4); t.add_column("Room",style="bright_cyan"); t.add_column("Category"); t.add_column("Description"); t.add_column("🟢",justify="right"); t.add_column("🔒",width=3)
        for rm in rooms:
            t.add_row(rm.get("icon","💬"), f"#{rm['name']}", rm.get("category","") or "", rm.get("description","") or "", str(rm.get("online",0)), "🔒" if rm.get("has_password") else "")
        console.print(t)
        console.print("[dim]  Join: trmsg chat → /join <room>[/dim]\n")
    except APIError as e: print_error(f"Failed: {e.message}")
    finally: await api.close()
