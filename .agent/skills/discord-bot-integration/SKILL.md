---
name: discord-bot-integration
description: Guide for integrating a Discord bot for trading notifications and control.
---

# Discord Bot Integration

## 1. Setup
- **Library:** `pip install discord.py` (or `nextcord`, `py-cord`).
- **Permissions:** Create App in Discord Developer Portal -> Bot -> Enable "Message Content Intent".
- **Invite:** Generate OAuth2 URL with `bot` scope and `Send Messages`, `Embed Links` permissions.

## 2. Structure
- Run the Discord bot in a separate thread or async task alongside the main trading loop (using `asyncio`).
- **Channels:** Configure separate Channel IDs for:
    - `#signals` (Trade entries)
    - `#pnl` (Closed trade reports)
    - `#errors` (System alerts)
    - `#logs` (Verbose debug info)

## 3. Features
- **Embeds:** Use Rich Embeds for signals (Color coding: Green for Buy, Red for Sell).
    - Fields: Price, TP/SL, R:R, Strategy Name.
- **Commands (Slash Commands):**
    - `/status` - Bot health, open positions, balance.
    - `/balance` - Current equity curve.
    - `/stop` / `/start` - Emergency controls (restrict to Admin role).
    - `/force_close <symbol>` - Manually close a position.

## 4. Code Pattern (Async)
```python
import discord
from discord.ext import commands

bot = commands.Bot(command_prefix='/', intents=discord.Intents.default())

@bot.command()
async def status(ctx):
    await ctx.send(embed=create_status_embed())

async def start_discord():
    await bot.start(TOKEN)
```

## 5. Rate Limits
- Discord API has strict rate limits. Implement a queue system for messages if sending high-frequency logs to avoid 429 errors.
