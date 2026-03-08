# Axiom 💣
> The most unhinged utility bot you'll ever add.

![Python](https://img.shields.io/badge/Python-3.14-blue?style=flat-square&logo=python)
![discord.py](https://img.shields.io/badge/discord.py-2.3.2-5865F2?style=flat-square&logo=discord)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)

---

## Features

| Command | Description |
|---|---|
| 💣 `/pingbomb` | Spam ping a user with pause, stop & anonymous mode |
| 💣 `/pingbomb_status` | Check your active session |
| 👻 `/ghostping` | Ghost ping a user up to 10x |
| 👻 `/massghost` | Ghost ping up to 20 users at once |
| ⏰ `/schedule_pingbomb` | Schedule a pingbomb to fire after a delay |
| ⏰ `/schedule_list` | View your pending scheduled jobs |
| ⏰ `/schedule_cancel` | Cancel a scheduled job (Admin) |
| 📢 `/echo` | Make the bot say something anonymously |
| ⚙️ `/settings` | View & manage server settings (Admin) |
| 🛡️ `/admin_*` | Admin controls for sessions & cooldowns |

---

## Architecture

Axiom is designed with a modular architecture to keep commands, services, and core systems separated.
```
axiom-bot-python
│
├─ bot/        # Discord client & startup logic
├─ cogs/       # Slash commands and command groups
├─ core/       # Core systems (sessions, cooldowns, rate limiting)
├─ services/   # Background tasks and scheduled jobs
├─ ui/         # Discord button views and UI interactions
├─ util/       # Helper utilities and shared functions
├─ data/       # Persistent config and storage
│
├─ main.py     # Bot entry point
├─ config.py   # Environment configuration
└─ requirements.txt
```

---

## Setup

### 1. Clone the repo
```bash
git clone https://github.com/sarawagh27/axiom-bot-python.git
cd axiom-bot-python
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure environment
```bash
cp .env.example .env
```
Fill in your `.env` file:
```
DISCORD_TOKEN=your_bot_token_here
DEV_GUILD_ID=your_server_id_here
```

### 4. Run the bot
```bash
python main.py
```

---

## Hosting
Axiom is designed to run 24/7 on [Render](https://render.com) with [UptimeRobot](https://uptimerobot.com) keeping it alive.

- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `python main.py`
- **Health endpoint:** `https://your-app.onrender.com/health`

---

## Required Bot Permissions
- View Channels
- Send Messages
- Manage Messages
- Embed Links
- Read Message History
- Mention Everyone
- Use Slash Commands

---

*Built with 💙 using discord.py*
