"""
EVILISM — main.py
Launches both the Discord bot and the Flask backend API in a single process.

Usage:
    python main.py

The Flask server runs in a background thread.
The Discord bot runs in the main asyncio event loop.
"""

import asyncio
import logging
import threading

from config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("evilism.main")


def run_backend():
    """Run the Flask backend in a background thread."""
    from backend import app
    log.info(f"Starting backend on {Config.BACKEND_HOST}:{Config.BACKEND_PORT}")
    app.run(host=Config.BACKEND_HOST, port=Config.BACKEND_PORT, debug=False, use_reloader=False)


def run_bot():
    """Run the Discord bot (blocking)."""
    from bot import bot, db
    from backend import get_security_queue
    import discord

    # Background task: drain the security log queue and post to Discord
    async def drain_security_queue():
        await bot.wait_until_ready()
        q = get_security_queue()
        while not bot.is_closed():
            while not q.empty():
                item = q.get()
                for guild in bot.guilds:
                    channel = discord.utils.get(guild.text_channels, name=Config.CHANNEL_SECURITY_LOGS)
                    if channel:
                        msg = (
                            f"📋 **New Application Received**\n"
                            f"User: <@{item['discord_id']}> (`{item['discord_username']}` — `{item['discord_id']}`)\n"
                            f"Preview of Q1: *\"{item['preview']}...\"*\n\n"
                            f"Use `/viewapp {item['discord_id']}` to read the full application.\n"
                            f"Use `/approve {item['discord_id']}` or `/deny {item['discord_id']} <reason>` to act on it."
                        )
                        try:
                            await channel.send(msg)
                        except:
                            pass
            await asyncio.sleep(5)

    # Use the default loop instead of creating a new one
    async def main():
        async with bot:
            bot.loop.create_task(drain_security_queue())
            await bot.start(Config.BOT_TOKEN)

    asyncio.run(main())



if __name__ == "__main__":
    # Start Flask backend in a daemon thread
    backend_thread = threading.Thread(target=run_backend, daemon=True)
    backend_thread.start()
    log.info("Backend thread started.")

    # Run the Discord bot in the main thread (blocking)
    run_bot()
