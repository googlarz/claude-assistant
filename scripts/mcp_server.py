#!/usr/bin/env python3
"""
Assistant Calendar — MCP Server

Exposes all calendar operations as native Claude tools.
When connected via MCP, Claude uses these directly instead of shelling out to Python —
faster, no string parsing, works in any MCP-compatible client.

Install:  pip3 install mcp
Activate: add to ~/.claude/settings.json (see bottom of this file)
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    import calendar as cal_module
except ImportError as e:
    print(f"ERROR importing calendar module: {e}", file=sys.stderr)
    sys.exit(1)

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp import types
except ImportError:
    print("ERROR: MCP SDK not installed.", file=sys.stderr)
    print("Install: pip3 install mcp", file=sys.stderr)
    sys.exit(1)


app = Server("assistant-calendar")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="calendar_add",
            description=(
                "Add an event to the Assistant calendar. "
                "Automatically looks up preferences (duration, color, reminder) for the event type. "
                "Appends project path + session transcript link to description."
            ),
            inputSchema={
                "type": "object",
                "required": ["title", "start", "end"],
                "properties": {
                    "title":       {"type": "string", "description": "Event title"},
                    "start":       {"type": "string", "description": "Start datetime ISO 8601"},
                    "end":         {"type": "string", "description": "End datetime ISO 8601"},
                    "description": {"type": "string", "description": "Context from the conversation"},
                    "color":       {"type": "string", "description": "Override color"},
                    "reminder":    {"type": "integer","description": "Override reminder minutes"},
                    "recurrence":  {"type": "string", "description": "RRULE string for recurring events"},
                },
            },
        ),
        types.Tool(
            name="calendar_list",
            description="List upcoming and recent Assistant calendar events. Call before adding to avoid duplicates.",
            inputSchema={
                "type": "object",
                "properties": {
                    "days_back":  {"type": "integer", "default": 3,  "description": "Days to look back"},
                    "days_ahead": {"type": "integer", "default": 7,  "description": "Days to look ahead"},
                },
            },
        ),
        types.Tool(
            name="calendar_reschedule",
            description="Move an Assistant calendar event by a relative shift or to a specific new time.",
            inputSchema={
                "type": "object",
                "required": ["title"],
                "properties": {
                    "title":     {"type": "string", "description": "Event title to search for"},
                    "shift":     {"type": "string", "description": "Relative shift: +2h, +30m, +1d, -1h"},
                    "new_start": {"type": "string", "description": "New absolute start datetime ISO 8601"},
                },
            },
        ),
        types.Tool(
            name="calendar_match_prefs",
            description="Look up preference rules for an event title (duration, color, reminder).",
            inputSchema={
                "type": "object",
                "required": ["title"],
                "properties": {
                    "title": {"type": "string"},
                },
            },
        ),
        types.Tool(
            name="calendar_update_prefs",
            description="Add or update a preference rule. Use when user says 'always book X min for Y'.",
            inputSchema={
                "type": "object",
                "required": ["match"],
                "properties": {
                    "match":         {"type": "string",  "description": "Keyword to match"},
                    "duration":      {"type": "integer", "description": "Duration in minutes"},
                    "color":         {"type": "string"},
                    "reminder":      {"type": "integer", "description": "Reminder in minutes"},
                    "calendar_name": {"type": "string",  "description": "Route to a different calendar"},
                    "recurrence":    {"type": "string",  "description": "RRULE string"},
                },
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "calendar_add":
            result = _add(arguments)
        elif name == "calendar_list":
            result = _list(arguments)
        elif name == "calendar_reschedule":
            result = _reschedule(arguments)
        elif name == "calendar_match_prefs":
            result = json.dumps(cal_module.match_preferences(arguments["title"]), indent=2)
        elif name == "calendar_update_prefs":
            result = _update_prefs(arguments)
        else:
            result = f"Unknown tool: {name}"
    except Exception as e:
        result = f"ERROR: {e}"
    return [types.TextContent(type="text", text=result)]


def _add(args: dict) -> str:
    config      = cal_module.load_config()
    calendar_id = config.get("calendar_id")
    if not calendar_id:
        return "NOT SET UP — run: python3 calendar.py setup"

    service  = cal_module.get_service()
    pref     = cal_module.match_preferences(args["title"], args.get("description", ""))
    cal_id   = cal_module.effective_calendar_id(pref, config, service)
    tz_str   = config.get("timezone", "UTC")
    color    = args.get("color")    or pref.get("color", "bold_blue")
    reminder = args.get("reminder") or pref.get("reminder_minutes", 10)

    event_body = {
        "summary":     args["title"],
        "description": cal_module.build_description(args.get("description", "")),
        "start":       {"dateTime": args["start"], "timeZone": tz_str},
        "end":         {"dateTime": args["end"],   "timeZone": tz_str},
        "colorId":     cal_module.COLOR_MAP.get(color, "9"),
        "reminders":   {"useDefault": False, "overrides": [{"method": "popup", "minutes": reminder}]},
    }
    if args.get("recurrence"):
        event_body["recurrence"] = [args["recurrence"]]

    result = service.events().insert(calendarId=cal_id, body=event_body).execute()
    link   = result.get("htmlLink", "")
    lines  = [f"✅ Added: {args['title']}", f"   {args['start']} → {args['end']} ({tz_str})"]
    if pref.get("matched"):
        lines.append(f"   (used '{pref['matched']}' preference)")
    if link:
        lines.append(f"   🔗 {link}")
    return "\n".join(lines)


def _list(args: dict) -> str:
    config      = cal_module.load_config()
    calendar_id = config.get("calendar_id")
    if not calendar_id:
        return "NOT SET UP"

    service    = cal_module.get_service()
    now        = datetime.now(timezone.utc)
    days_back  = args.get("days_back", 3)
    days_ahead = args.get("days_ahead", 7)

    result = service.events().list(
        calendarId=calendar_id,
        timeMin=(now - timedelta(days=days_back)).isoformat(),
        timeMax=(now + timedelta(days=days_ahead)).isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=20,
    ).execute()

    events = result.get("items", [])
    if not events:
        return f"No events in past {days_back}d / next {days_ahead}d."

    lines = [f"Assistant calendar — past {days_back}d / next {days_ahead}d\n"]
    for ev in events:
        dt_str = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date", "")
        try:
            dt      = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            display = dt.strftime("%a %b %-d  %H:%M")
            marker  = "✓ " if dt < now else "  "
        except Exception:
            display = dt_str
            marker  = "  "
        lines.append(f"{marker}{display}  {ev.get('summary', '(no title)')}  [{ev['id'][:8]}]")
    return "\n".join(lines)


def _reschedule(args: dict) -> str:
    import re
    config      = cal_module.load_config()
    service     = cal_module.get_service()
    calendar_id = config.get("calendar_id", "primary")
    now         = datetime.now(timezone.utc)

    result = service.events().list(
        calendarId=calendar_id,
        timeMin=(now - timedelta(days=7)).isoformat(),
        timeMax=(now + timedelta(days=30)).isoformat(),
        q=args["title"], singleEvents=True, orderBy="startTime", maxResults=1,
    ).execute()

    events = result.get("items", [])
    if not events:
        return f"No event found: {args['title']}"

    event      = events[0]
    ev_id      = event["id"]
    old_start  = datetime.fromisoformat(event["start"]["dateTime"].replace("Z", "+00:00"))
    old_end    = datetime.fromisoformat(event["end"]["dateTime"].replace("Z", "+00:00"))
    duration   = old_end - old_start
    tz_str     = event["start"].get("timeZone") or config.get("timezone", "UTC")

    if args.get("shift"):
        m = re.match(r'^([+-]?)(\d+)([hmd])$', args["shift"].strip())
        if not m:
            return f"Invalid shift '{args['shift']}'. Use: +2h  +30m  +1d  -1h"
        sign  = -1 if m.group(1) == "-" else 1
        n     = int(m.group(2))
        unit  = m.group(3)
        delta = timedelta(
            hours=n*sign   if unit == "h" else 0,
            minutes=n*sign if unit == "m" else 0,
            days=n*sign    if unit == "d" else 0,
        )
        new_start = old_start + delta
    elif args.get("new_start"):
        new_start = cal_module.parse_time(args["new_start"])
    else:
        return "Provide 'shift' (+2h / +30m / +1d) or 'new_start'."

    new_end       = new_start + duration
    new_start_iso = new_start.strftime("%Y-%m-%dT%H:%M:%S")
    new_end_iso   = new_end.strftime("%Y-%m-%dT%H:%M:%S")

    service.events().patch(
        calendarId=calendar_id, eventId=ev_id,
        body={
            "start": {"dateTime": new_start_iso, "timeZone": tz_str},
            "end":   {"dateTime": new_end_iso,   "timeZone": tz_str},
        },
    ).execute()
    return f"✅ Rescheduled: {event.get('summary')} → {new_start_iso} ({tz_str})"


def _update_prefs(args: dict) -> str:
    prefs    = cal_module.load_preferences()
    patterns = prefs.get("patterns", [])

    existing_idx = None
    for i, p in enumerate(patterns):
        if args["match"].lower() in [k.lower() for k in p.get("match", [])]:
            existing_idx = i
            break

    pattern = patterns[existing_idx] if existing_idx is not None else {"match": [args["match"]]}
    for key in ("duration", "color", "reminder", "calendar_name", "recurrence"):
        api_key  = {"duration": "duration_minutes", "reminder": "reminder_minutes"}.get(key, key)
        if args.get(key) is not None and args[key] != "":
            pattern[api_key] = args[key]

    if existing_idx is not None:
        patterns[existing_idx] = pattern
    else:
        patterns.append(pattern)

    prefs["patterns"] = patterns
    cal_module.save_preferences(prefs)
    return f"✅ Preference saved for '{args['match']}':\n{json.dumps(pattern, indent=2)}"


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())


# ─── To activate ─────────────────────────────────────────────────────────────
# Add to ~/.claude/settings.json:
#
# "mcpServers": {
#   "assistant-calendar": {
#     "command": "python3",
#     "args": ["/Users/dawid/.claude/skills/assistant/scripts/mcp_server.py"]
#   }
# }
