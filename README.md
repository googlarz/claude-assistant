# 🗓️ Assistant — Claude Code Skill

**A personal calendar and task manager built as a Claude Code skill.**

Write rich, context-aware entries directly to Google Calendar from inside any Claude Code
conversation. Every entry is linked back to the exact conversation that created it — so when
the notification fires, you know exactly what it's about and why it matters.

---

## ✨ What makes it different

Most calendar tools add an event title and maybe a time. This skill adds **context**:

```
• Sync API keys with Marco before the deploy
• Why: production deploy is Friday 3pm, keys expire Thursday
• How: Marco's calendar link → book 30min any time Thursday morning

────────────────────────────────────────────────
📁  /Users/you/projects/api-migration
🔗  Session: f1936594-4c90-43bf-97fe-70fce545a8e2
📄  Transcript: ~/.claude/projects/.../f1936594.jsonl
🕐  Added: 2026-03-01 14:32 UTC
```

When the reminder fires on your phone at 9am Thursday, you don't need to remember anything —
the context is right there in the notification.

---

## 🚀 Features

| Feature | Description |
|---------|-------------|
| 📅 **Google Calendar** | Real events — phone notifications, shared calendars, invites |
| 🔍 **Conflict detection** | Warns before double-booking, shows what's in the way |
| ⏱️ **Free slot finder** | Queries your actual schedule for open windows |
| 🎨 **Preference system** | "standups are always 15min bold_blue" — learns your defaults |
| 📋 **Task list** | Lightweight local tasks for things without a time |
| 👤 **User profile** | Work hours, preferred name, schedule style (morning/evening) |
| 🔄 **Recurring events** | Full RRULE support — daily, weekly, monthly series |
| 👥 **Attendees** | Send Google Calendar invites directly from the conversation |
| 🟡 **Prep blocks** | Auto-insert a yellow "Prep: [event]" block before meetings |
| 📦 **Bulk reschedule** | Move all events on a day: "I'm sick, push Tuesday to Wednesday" |
| 🗑️ **Delete** | Remove events cleanly with confirmation |
| 🔎 **Search** | Find past/future events by keyword |
| ☀️ **Daily digest** | Shows today's events + tasks every time you open Claude Code |
| 📡 **MCP server** | Optional native tool access without shell-out overhead |

---

## 📋 5 Sample Use Cases

---

### 1 — The Follow-Up You'd Forget

You're deep in a conversation about a client API migration. At the end, you say:

> *"remind me to follow up with Marco about the API keys next Thursday morning"*

Claude:
1. Checks your calendar — Thursday 9am is free
2. Matches preferences → `follow up` = 15min, bold_blue
3. Builds description with action items from this conversation
4. Shows preview: title, time, reminder, colour
5. You confirm → event appears in your calendar with a 10min popup reminder

**What you see in the notification Thursday 8:50am:**
```
📌 Follow up: Marco — API keys
• Confirm new API keys are rotated before deploy
• Keys expire Thursday, deploy is Friday 3pm
• Marco's email: marco@company.com
```

---

### 2 — The Deadline That Actually Reminds You

You're reviewing a PR and realise it must merge by Friday 5pm:

> *"don't let me forget — this PR has to merge before Friday 5pm"*

Claude:
1. Matches `deadline` preference → `bold_red`, 2-hour reminder
2. Detects conflict: "Code review 15:30–16:30 on Friday"
3. Asks whether to proceed — you say yes
4. Creates event: **Deadline: PR #204 — merge before 5pm** in bold red
5. Notification fires at 15:00 Friday — hard to miss

---

### 3 — The Recurring Standup You Set Up Once

> *"set up my daily standup — 9:15am weekdays, 15 minutes"*

Claude:
1. Saves preference: `standup` = 15min, RRULE weekly Mon–Fri
2. Creates a single Google Calendar recurring event
3. Shows up in your calendar for every weekday going forward
4. Next time you say "add the standup" — it already knows it's 15min weekdays

---

### 4 — The Deep Work Block You Actually Protect

You're slipping behind on a design doc and say:

> *"I need 2 uninterrupted hours for the architecture doc this week — when am I free?"*

Claude:
1. Calls `free --date "this week" --duration 120`
2. Checks your **actual** calendar (primary + Assistant) for gaps
3. Returns: *"Thursday 10:00–12:00 (120min), Friday 14:00–17:00 (180min)"*
4. You pick Thursday
5. Adds: **Deep work: architecture doc** in purple with no interruptions blocked

---

### 5 — The Meeting That Comes With Prep

> *"book a 1:1 with Sarah next Monday at 2pm, send her an invite, and give me 15 minutes to prep"*

Claude:
1. Matches `1:1` → 45min from saved preference
2. Checks conflicts → Monday 2pm is clear
3. Shows preview: attendee (sarah@company.com), prep block, time, colour
4. You confirm → two events created:
   - 🟡 **Prep: 1:1 Sarah** 13:45–14:00 (yellow, no reminder)
   - 🔵 **1:1 Sarah — weekly sync** 14:00–14:45 (bold blue, 10min reminder)
5. Sarah receives a Google Calendar invitation email

---

## 📦 Installation

### 1. Clone the skill

```bash
git clone https://github.com/googlarz/assistant-skill ~/.claude/skills/assistant
```

### 2. Install Python dependencies

```bash
pip3 install google-api-python-client google-auth-oauthlib google-auth-httplib2

# Optional: natural language time parsing ("tomorrow 3pm", "next Friday EOD")
pip3 install dateparser

# Optional: MCP server for native Claude tool access
pip3 install mcp
```

### 3. Get Google Calendar credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project → Enable **Google Calendar API**
3. **Credentials** → Create **OAuth 2.0 Client ID** (Desktop app) → Download JSON
4. Save as `~/.claude/skills/assistant/credentials.json`

> Already using **proactive-claw**? Your credentials are reused automatically.

### 4. Run setup

```bash
python3 ~/.claude/skills/assistant/scripts/calendar.py setup
```

Authenticates with Google, auto-detects your timezone, and creates (or selects)
a dedicated "Assistant" calendar.

### 5. Set up your profile

```bash
python3 ~/.claude/skills/assistant/scripts/calendar.py profile --setup
```

Stores your name, work hours, and schedule style so the assistant can warn you about
out-of-hours bookings and find free slots accurately.

### 6. Add the SessionStart hook (daily digest)

Add to `~/.claude/settings.json`:

```json
"hooks": {
  "SessionStart": [{
    "hooks": [{
      "type": "command",
      "command": "python3 ~/.claude/skills/assistant/scripts/calendar.py list --digest 2>/dev/null; python3 ~/.claude/skills/assistant/scripts/tasks.py today 2>/dev/null; true"
    }]
  }]
}
```

---

## 🛠️ Command Reference

### Calendar

```bash
CAL="python3 ~/.claude/skills/assistant/scripts/calendar.py"

$CAL setup                                    # First-time auth + calendar
$CAL status                                   # Config + profile summary
$CAL list [--days-back 3] [--days-ahead 7]   # Browse events
$CAL list --digest                            # Day-aware: week Mon, today other days
$CAL add --title "..." --start "..." --end "..."  [--attendees "a@b.com"] [--prep-minutes 15]
$CAL delete --title "..."
$CAL reschedule --title "..." --shift "+2h"  # Single event
$CAL reschedule --date "Tuesday" --shift "+1d"  # Bulk: move whole day
$CAL search "keyword"
$CAL free --date "this week" --duration 90
$CAL profile --setup
$CAL match --title "standup"                 # Returns preference JSON
$CAL update-prefs --match "standup" --duration 15 --color "bold_blue"
```

### Tasks

```bash
TASKS="python3 ~/.claude/skills/assistant/scripts/tasks.py"

$TASKS add "Buy milk" --priority low --category personal
$TASKS add "Review PR #204" --priority high --due 2026-03-05 --category work
$TASKS list
$TASKS today
$TASKS week
$TASKS overdue
$TASKS complete "buy milk"
$TASKS delete "buy milk"
$TASKS category work
$TASKS summary
```

---

## ⚙️ Configuration

### preferences.json — Event defaults by type

```json
{
  "patterns": [
    {
      "match": ["standup", "stand-up", "daily sync"],
      "duration_minutes": 15,
      "color": "bold_blue",
      "reminder_minutes": 5
    },
    {
      "match": ["deadline", "due:", "ship by", "release"],
      "duration_minutes": 15,
      "color": "bold_red",
      "reminder_minutes": 120
    },
    {
      "match": ["1:1", "one on one", "one-on-one"],
      "duration_minutes": 45,
      "color": "bold_blue",
      "reminder_minutes": 10
    }
  ],
  "defaults": {
    "duration_minutes": 30,
    "color": "bold_blue",
    "reminder_minutes": 10
  }
}
```

Claude can update this file for you:
> *"always book 45 minutes for 1:1s"* → `update-prefs --match "1:1" --duration 45`

### config.json — Generated by setup

```json
{
  "calendar_id": "your-calendar-id@group.calendar.google.com",
  "calendar_name": "Assistant",
  "timezone": "Europe/Warsaw",
  "profile": {
    "name": "Dawid",
    "preferred_name": "Dawid",
    "work_hours": { "start": "09:00", "end": "18:00" },
    "working_style": "morning",
    "no_schedule_before": "09:00",
    "no_schedule_after": "20:00",
    "work_days": [0, 1, 2, 3, 4]
  }
}
```

---

## 🎨 Color Reference

| Name | Calendar colour | Best for |
|------|----------------|----------|
| `bold_red` | 🔴 Tomato | Deadlines, launches |
| `bold_blue` | 🔵 Blueberry | Meetings, calls |
| `bold_green` | 🟢 Sage | Milestones, wins |
| `orange` | 🟠 Tangerine | Reviews, demos |
| `purple` | 🟣 Grape | Deep work, learning |
| `yellow` | 🟡 Banana | Prep blocks |
| `turquoise` | 🩵 Peacock | Health, fitness |
| `green` | 💚 Basil | Personal, social |

---

## 📡 MCP Server (Optional)

Expose the assistant as native Claude tools instead of shell-out commands:

```json
"mcpServers": {
  "assistant-calendar": {
    "command": "python3",
    "args": ["/Users/YOUR_NAME/.claude/skills/assistant/scripts/mcp_server.py"]
  }
}
```

Tools exposed: `calendar_add`, `calendar_list`, `calendar_reschedule`,
`calendar_match_prefs`, `calendar_update_prefs`

---

## 🔒 Privacy

- All data stays local or in your own Google Calendar
- `token.json` and `credentials.json` are in `.gitignore` — never committed
- No third-party servers involved
- The session transcript link in entries points to your local `~/.claude/projects/` directory

---

## 📁 File Structure

```
~/.claude/skills/assistant/
├── SKILL.md              ← Claude reads this (skill instructions)
├── README.md             ← This file
├── preferences.json      ← Event-type defaults (safe to edit / commit)
├── config.json           ← Generated by setup (contains tokens path, not committed)
├── tasks.json            ← Local task list
├── credentials.json      ← Google API credentials  ← NOT committed
├── token.json            ← Google OAuth token       ← NOT committed
└── scripts/
    ├── calendar.py       ← Main backend (11 commands)
    ├── tasks.py          ← Task list (9 commands)
    └── mcp_server.py     ← Optional MCP server
```

---

## 🤝 Related

- [proactive-claw](https://github.com/googlarz/proactive-claw) — Google Calendar daemon for
  Claude Code with background monitoring and webhook support

---

*Built as a Claude Code skill. Runs entirely on your machine.*
