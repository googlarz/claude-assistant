---
name: assistant
description: >
  Personal calendar and task assistant. Invoke when the user mentions scheduling,
  reminders, follow-ups, deadlines, meetings, tasks, or asks to "remember" something.
  Writes rich context-aware entries to Google Calendar with conversation links,
  manages a local task list, detects scheduling conflicts, and respects work-hour preferences.
---

# Assistant — Personal Calendar & Task Manager

> **Invoke with `/assistant`** — Activated whenever a user mentions scheduling, follow-ups,
> reminders, deadlines, meetings, tasks, or asks to "remember" something from the conversation.

---

## What This Skill Does

Transforms Claude into a proactive personal assistant that:
- Writes **rich, context-aware entries** directly to the user's Google Calendar
- Maintains a **local task list** for things that don't need a calendar slot
- Detects **scheduling conflicts** before writing
- Respects the user's **work hours and style** preferences
- Links every calendar entry back to the **exact conversation transcript** it came from

---

## Session Start — Daily Digest

At the beginning of every Claude Code session, the SessionStart hook automatically runs:

```
📅 Week ahead:              ← on Monday
   or
   Today:                   ← other days
```

If you see upcoming events in the session preamble, note them before starting work.

---

## Workflow — Step by Step

### Step 0 — Verify setup

```bash
python3 ~/.claude/skills/assistant/scripts/calendar.py status
```

- If output is `NOT SET UP`, run `setup` and stop until the user completes it
- If profile is missing, suggest: *"Run `calendar.py profile --setup` to personalise your assistant"*

---

### Step 1 — Check for duplicates and free time

Before adding anything, run both checks in parallel:

```bash
# Check what's already there
python3 ~/.claude/skills/assistant/scripts/calendar.py list --days-back 0 --days-ahead 7

# Check for free slots if user needs scheduling help
python3 ~/.claude/skills/assistant/scripts/calendar.py free --date "this week" --duration 60
```

If an event with the same title already exists in the next 7 days, **ask the user** whether to
reschedule the existing one or add a new entry.

---

### Step 2 — Match preferences

```bash
python3 ~/.claude/skills/assistant/scripts/calendar.py match --title "TITLE" --description "DESCRIPTION"
```

Returns JSON with `duration_minutes`, `color`, `reminder_minutes`, `matched`.
Use these as defaults — the user's preferences are the starting point, not overrides.

---

### Step 3 — Resolve time

- If the user gave a specific time → use it directly
- If vague ("tomorrow afternoon", "end of week") → resolve to a concrete ISO datetime
- If no time given → ask: *"What time should I book this for?"*
- Use dateparser naturally: `"tomorrow 3pm"`, `"next Monday 10am"`, `"Friday EOD"`

**Never assume a time the user didn't provide.**

---

### Step 4 — Build a rich description

Every calendar entry should include actionable context so the user knows exactly what to do
when the notification fires:

```
[2-3 bullet points summarising what was decided / what the user needs to do]
• What: [specific action or topic]
• Why:  [why this matters / what happens if missed]
• How:  [any relevant links, files, people, or steps]

────────────────────────────────────────────────
📁  /path/to/current/project
🔗  Session: [CLAUDE_SESSION_ID]
📄  Transcript: ~/.claude/projects/.../.jsonl
🕐  Added: YYYY-MM-DD HH:MM UTC
```

The `build_description()` function handles the footer automatically — you only need to write
the bullet points.

---

### Step 5 — Add the event (with confirmation)

```bash
python3 ~/.claude/skills/assistant/scripts/calendar.py add \
  --title "TITLE" \
  --start "YYYY-MM-DDTHH:MM:SS" \
  --end   "YYYY-MM-DDTHH:MM:SS" \
  --description "bullet points here" \
  [--attendees "a@b.com,c@d.com"] \
  [--prep-minutes 15] \
  [--recurrence "RRULE:FREQ=WEEKLY;BYDAY=MO"]
```

The script will:
1. Warn if outside work hours (from profile)
2. Show conflicts if any exist at that time
3. Display a confirmation preview
4. Ask **Y/n** before writing

Use `--yes` / `-y` only when the user has already confirmed in the chat.

---

## All Commands — Quick Reference

### Calendar Commands

| Command | Purpose | Key flags |
|---------|---------|-----------|
| `setup` | First-time OAuth + calendar selection | — |
| `status` | Show config + profile | — |
| `list` | Browse events | `--days-back N` `--days-ahead N` `--digest` |
| `match` | Get preference for a title | `--title` `--description` |
| `add` | Create an event | `--title` `--start` `--end` `--description` `--attendees` `--prep-minutes` `--recurrence` `--yes` |
| `delete` | Remove an event | `--title` `--yes` |
| `reschedule` | Move event(s) | `--title` `--shift` `--new-start` OR `--date` `--shift` (bulk) |
| `search` | Find events by keyword | `query` `--days-back N` `--days-ahead N` |
| `free` | Find open time slots | `--date` `--duration N` `--days N` |
| `profile` | View / set work hours, name, style | `--setup` `--work-start` `--work-end` `--style` `--no-before` `--no-after` |
| `update-prefs` | Add / change preference rules | `--match` `--duration` `--color` `--reminder` `--calendar-name` `--recurrence` |

### Task Commands

```bash
TASKS="python3 ~/.claude/skills/assistant/scripts/tasks.py"

$TASKS add "TITLE" [--priority high|medium|low] [--due YYYY-MM-DD] [--category work]
$TASKS list
$TASKS today
$TASKS week
$TASKS overdue
$TASKS complete "title or id"
$TASKS delete  "title or id"
$TASKS category [name]
$TASKS summary
```

---

## Calendar vs Task — Decision Guide

| Situation | Use Calendar | Use Task |
|-----------|-------------|----------|
| Has a specific time | ✅ | — |
| Needs phone/desktop notification | ✅ | — |
| Involves other people (invite) | ✅ | — |
| "Remember to do X" (no time) | — | ✅ |
| Recurring habit to track | ✅ | — |
| Shopping / errand list | — | ✅ |
| Deadline with a due date | ✅ | ✅ both |

When in doubt: **calendar** for time-anchored things, **task** for everything else.

---

## Color Guide

| Color | Use for |
|-------|---------|
| `bold_red` (11) | Deadlines, launches, critical blockers |
| `bold_blue` (9) | Meetings, calls, standups |
| `bold_green` (10) | Milestones, completions, wins |
| `red` (4) | Urgent reminders |
| `orange` (6) | Reviews, demos, presentations |
| `purple` (3) | Learning, courses, deep work |
| `yellow` (5) | Prep blocks (auto-set) |
| `turquoise` (7) | Personal: health, fitness |
| `green` (2) | Personal: social, fun |
| `blue` (1) | Flexible / low priority |

---

## Title Guide

Good calendar titles are **scannable at a glance** in the notification:

| ✅ Good | ❌ Avoid |
|--------|---------|
| `Follow up: Marco — API keys` | `Follow up with Marco about the API keys issue` |
| `Deadline: v2.1 release` | `v2.1 needs to ship` |
| `Review: PR #204 auth refactor` | `Look at the PR` |
| `Prep: Investor call @ 2pm` | `Prepare for investor call` |
| `1:1 Sarah — Q1 goals` | `Meeting with Sarah` |

Format: `[Type]: [Subject] — [Key detail]`

---

## Recurring Events

Use RRULE strings:

```
RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR     ← every weekday
RRULE:FREQ=WEEKLY;BYDAY=MO                  ← every Monday
RRULE:FREQ=MONTHLY;BYDAY=1MO               ← first Monday of every month
RRULE:FREQ=DAILY;COUNT=10                  ← 10 times then stop
```

---

## Conflict Handling

When `add` detects a conflict, it shows:
```
⚠️  Time conflict — 2 existing event(s):
   • Daily standup  2026-03-01 09:00
   • Team sync      2026-03-01 09:15

Schedule anyway? [y/N]:
```

If user says yes → pass `--yes` and proceed.
If user says no → offer to find free time: `free --date "today" --duration 30`

---

## Attendees & Meeting Invites

```bash
python3 ~/.claude/skills/assistant/scripts/calendar.py add \
  --title "Sync: backend API design" \
  --start "2026-03-05T14:00:00" \
  --end   "2026-03-05T15:00:00" \
  --attendees "marco@company.com,sarah@company.com" \
  --prep-minutes 15
```

⚠️ **Note**: `--attendees` sends real Google Calendar email invitations. Always confirm with
the user before passing attendee emails.

---

## Bulk Reschedule

Move all events on a given day:
```bash
python3 ~/.claude/skills/assistant/scripts/calendar.py reschedule \
  --date "Tuesday" \
  --shift "+1d"
```

Useful when the user says "I'm sick tomorrow, move everything to Wednesday."

---

## 5 Sample Use Cases

### 1 — Mid-conversation follow-up booking

**User says:** *"remind me to send the invoice to client X next Tuesday"*

1. `status` → OK
2. `match --title "Invoice: Client X"` → defaults (30min, bold_blue, 10min reminder)
3. Resolves "next Tuesday" → `2026-03-10T09:00:00`
4. `add --title "Invoice: Client X — send" --start "2026-03-10T09:00" --end "2026-03-10T09:15" --description "• Send invoice for March work\n• Client: X\n• Check outstanding items first"`
5. Confirmation shown → user confirms → event created with transcript link

---

### 2 — Deadline with conflict detection

**User says:** *"the PR needs to be merged by Friday 5pm, don't forget"*

1. `match --title "Deadline: PR merge"` → `bold_red`, 120min reminder
2. `add` → conflict detected: *"Retro @ 16:00 on Friday"*
3. Shows conflict, asks user
4. User says *"that's fine, add it"* → `add --yes`
5. Entry added with bold_red + 2hr popup reminder

---

### 3 — Recurring standup setup

**User says:** *"add my daily standup, 9:15am every weekday, 15 minutes"*

1. `update-prefs --match "standup" --duration 15 --recurrence "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"`
2. `add --title "Daily Standup" --start "2026-03-02T09:15:00" --end "2026-03-02T09:30:00" --recurrence "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"`
3. One command creates a full recurring series in Google Calendar

---

### 4 — Find free time + deep work block

**User says:** *"I need 2 hours to write the design doc this week — when am I free?"*

1. `free --date "this week" --duration 120`
2. Output shows: *"Thu: 10:00–12:00 (120min), Fri: 14:00–17:00 (180min)"*
3. User picks Thursday 10am
4. `add --title "Deep work: design doc" --start "2026-03-05T10:00" --end "2026-03-05T12:00" --color "purple"`

---

### 5 — Meeting with attendees + prep block

**User says:** *"book a 1:1 with Sarah next Monday at 2pm, invite sarah@co.com, add 15 min prep"*

1. `match --title "1:1 Sarah"` → 45min (from saved preference), bold_blue
2. Conflict check → clear
3. `add --title "1:1 Sarah — weekly sync" --start "2026-03-09T14:00" --end "2026-03-09T14:45" --attendees "sarah@co.com" --prep-minutes 15`
4. Preview shows invite warning + prep block
5. User confirms → main event + "Prep: 1:1 Sarah" at 13:45 both created

---

## MCP Server (Optional Upgrade)

For native tool access without shell-out overhead:

```json
"mcpServers": {
  "assistant-calendar": {
    "command": "python3",
    "args": ["/Users/YOUR_NAME/.claude/skills/assistant/scripts/mcp_server.py"]
  }
}
```

Install: `pip3 install mcp`

---

## File Locations

| File | Purpose |
|------|---------|
| `~/.claude/skills/assistant/config.json` | Calendar ID, timezone, profile |
| `~/.claude/skills/assistant/preferences.json` | Event-type rules (duration, color, reminder) |
| `~/.claude/skills/assistant/tasks.json` | Local task list |
| `~/.claude/skills/assistant/token.json` | Google OAuth token (do not commit) |
| `~/.claude/skills/assistant/credentials.json` | Google API credentials (do not commit) |
