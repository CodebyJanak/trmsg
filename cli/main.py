"""trmsg - CLI Entry Point"""
import click, asyncio
from cli.config import config
from cli.ui.theme import print_banner, print_error, print_info, console

def require_auth():
    if not config.is_authenticated():
        print_error("Not logged in. Run [bold]trmsg login[/bold] first.")
        raise SystemExit(1)

@click.group()
@click.version_option("1.0.0", prog_name="trmsg")
def cli():
    """⚡ trmsg — Terminal Messaging Platform\n\nChat, share files, play games. All from your terminal."""
    pass

@cli.command()
def register():
    """Create a new trmsg account."""
    from cli.commands.auth import register_command
    asyncio.run(register_command())

@cli.command()
def login():
    """Login to your trmsg account."""
    from cli.commands.auth import login_command
    asyncio.run(login_command())

@cli.command()
def logout():
    """Logout from trmsg."""
    from cli.commands.auth import logout_command
    logout_command()

@cli.command()
@click.argument("username", required=False)
def chat(username):
    """Open the chat. Optionally DM someone: trmsg chat <username>"""
    require_auth()
    from cli.ui.chat_ui import ChatUI
    ui = ChatUI(username=config.username, target=username, theme=config.theme)
    asyncio.run(ui.run())

@cli.command()
@click.argument("username")
def add(username):
    """Send a friend request."""
    require_auth()
    from cli.commands.social import cmd_add
    asyncio.run(cmd_add(username))

@cli.command()
def friends():
    """Show your friends list."""
    require_auth()
    from cli.commands.social import cmd_friends
    asyncio.run(cmd_friends())

@cli.command()
def users():
    """Show online users."""
    require_auth()
    from cli.commands.social import cmd_users
    asyncio.run(cmd_users())

@cli.command()
def leaderboard():
    """Show the leaderboard."""
    require_auth()
    from cli.commands.social import cmd_leaderboard
    asyncio.run(cmd_leaderboard())

@cli.command()
def stats():
    """Show server statistics."""
    require_auth()
    from cli.commands.social import cmd_stats
    asyncio.run(cmd_stats())

@cli.command()
def rooms():
    """List public rooms."""
    require_auth()
    from cli.commands.social import cmd_rooms
    asyncio.run(cmd_rooms())

@cli.command()
@click.argument("username")
def whois(username):
    """Look up a user's profile and stats."""
    require_auth()
    from cli.commands.social import cmd_whois
    asyncio.run(cmd_whois(username))

@cli.command()
def profile():
    """View and edit your profile."""
    require_auth()
    from cli.commands.auth import profile_command
    asyncio.run(profile_command())

@cli.command(name="config")
def config_cmd():
    """Configure trmsg settings."""
    from cli.commands.auth import configure_command
    configure_command()

def main():
    cli()

if __name__ == "__main__":
    main()
