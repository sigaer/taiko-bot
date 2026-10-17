"""Source launcher for the standalone Taiko application."""
from taiko_bot.bootstrap import create_app

app = create_app()

if __name__ == "__main__":
    import nonebot
    nonebot.run()
