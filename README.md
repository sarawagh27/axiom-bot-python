<div align="center">

# ⚡ Axiom

**A powerful, modular Discord utility bot built with Python and discord.py.**

[![Python](https://img.shields.io/badge/Python-3.14-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![discord.py](https://img.shields.io/badge/discord.py-2.3.2-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discordpy.readthedocs.io)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Live-22c55e?style=for-the-badge)]()

*Pingbomb. Ghost ping. Schedule chaos. Echo anonymously.*

</div>

---

## Overview

Axiom is a feature-rich Discord bot designed for servers that want powerful utility commands with fine-grained admin control. Built with a modular architecture, every feature is isolated into its own cog — making it easy to extend, debug, and maintain.

---

## Features

### 💣 Pingbomb
Spam ping a target user with full session control. Supports pause, resume, stop, and an anonymous mode that hides the invoker's identity.

### 👻 Ghost Ping
Send pings that vanish instantly — the notification fires before Discord can delete the message. Ghost ping a single user up to 10 times, or unleash mass ghost pings on up to 20 users simultaneously.

### ⏰ Scheduled Pingbomb
Schedule a pingbomb to fire after a custom delay. Supports formats like `30s`, `5m`, `2h`. Admins can view and cancel any scheduled job by ID.

### 📢 Anonymous Echo
Make the bot deliver any message to any channel with zero trace. The slash command response is ephemeral — no one sees who typed it.

### ⚙️ Per-Server Configuration
Every server gets its own settings — max ping count, cooldowns, min intervals, allowed channels, and the ability to enable or disable commands entirely.

### 🛡️ Admin Controls
Full session management for admins — force-stop sessions, clear cooldowns, view active sessions across the server, and override any user's state.

---

## Command Reference

| Category | Command | Description |
|---|---|---|
| 💣 Pingbomb | `/pingbomb` | Start a pingbomb session with pause & stop controls |
| | `/pingbomb_status` | View your current active session |
| 👻 Ghost Ping | `/ghostping` | Ghost ping a user up to 10x |
| | `/massghost` | Ghost ping up to 20 users at once (up to 20x each) |
| ⏰ Scheduled | `/schedule_pingbomb` | Schedule a pingbomb for later |
| | `/schedule_list` | View your pending scheduled jobs |
| | `/schedule_cancel` | Cancel a job by ID *(Admin)* |
| 📢 Echo | `/echo` | Send an anonymous message to any channel |
| ⚙️ Settings | `/settings` | View this server's configuration |
| | `/settings_set_max_count` | Set the maximum ping count |
| | `/settings_set_cooldown` | Set the cooldown duration |
| | `/settings_set_min_interval` | Set the minimum ping interval |
| | `/settings_toggle_pingbomb` | Enable or disable pingbomb |
| | `/settings_add_channel` | Restrict commands to a channel |
| | `/settings_remove_channel` | Remove a channel restriction |
| | `/settings_reset` | Reset all settings to defaults |
| 🛡️ Admin | `/admin_sessions` | List all active sessions |
| | `/admin_stop_session` | Force-stop a user's session |
| | `/admin_stop_all` | Stop all active sessions |
| | `/admin_clear_cooldown` | Clear a user's cooldown |
| | `/admin_clear_all_cooldowns` | Clear all cooldowns |
| 🔧 Utility | `/ping` | Check bot latency |
| | `/status` | View bot runtime stats |
| | `/info` | About Axiom |
| | `/help` | Full command reference |

---

## Architecture

Axiom uses a clean, modular structure where each layer has a single responsibility.

```
axiom-bot-python/
│
├── bot/                  # Discord client, cog loader & error handler
├── cogs/                 # Slash command definitions (one file per feature)
├── core/                 # Session management, rate limiting, guild config
├── services/             # Audit logging & background services
├── ui/                   # Discord UI components (buttons, views)
├── util/                 # Shared helpers (permissions, time parsing)
├── data/                 # Persistent per-guild configuration (JSON)
├── logs/                 # Runtime and audit logs
│
├── main.py               # Entry point with smart reconnect logic
├── config.py             # Environment variable configuration
├── keep_alive.py         # Flask server for Render/UptimeRobot
└── requirements.txt
```

**Key design decisions:**
- Each cog is fully self-contained and independently loadable
- Guild configs persist across restarts via JSON storage in `data/`
- Rate limiting uses a token bucket algorithm per user + global bucket
- The bot uses a smart retry loop on startup — exponential backoff on 429s

---

## Getting Started

### Prerequisites
- Python 3.14+
- A Discord bot token ([Developer Portal](https://discord.com/developers/applications))

### Installation

**1. Clone the repository**
```bash
git clone https://github.com/sarawagh27/axiom-bot-python.git
cd axiom-bot-python
```

**2. Install dependencies**
```bash
pip install -r requirements.txt
```

**3. Configure environment**
```bash
cp .env.example .env
```

Edit `.env` with your credentials:
```env
DISCORD_TOKEN=your_bot_token_here
DEV_GUILD_ID=your_server_id_here
```

**4. Run the bot**
```bash
python main.py
```

---

## Hosting

Axiom is designed to run 24/7 on [Render](https://render.com) (free tier) with [UptimeRobot](https://uptimerobot.com) preventing spin-down.

| Setting | Value |
|---|---|
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python main.py` |
| Health Endpoint | `https://your-app.onrender.com/health` |

Set `DISCORD_TOKEN` and `DEV_GUILD_ID` as environment variables in the Render dashboard — never commit your token to Git.

---

## Required Bot Permissions

| Permission | Reason |
|---|---|
| Send Messages | Core functionality |
| Manage Messages | Ghost ping deletion |
| Embed Links | Rich embed responses |
| Read Message History | Session context |
| Mention Everyone | Ping functionality |
| Use Slash Commands | Command registration |

---

## Invite

To add Axiom to a server, generate an invite link from the [Discord Developer Portal](https://discord.com/developers/applications) under **OAuth2 → URL Generator**.

Required scopes: `bot` + `applications.commands`

---

<div align="center">

*Built with 💙 using [discord.py](https://discordpy.readthedocs.io)*

</div>
