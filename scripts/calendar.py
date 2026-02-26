#!/usr/bin/env python3
"""
Assistant Calendar — Claude Code skill backend

Commands:
  setup          OAuth + auto-detect timezone + calendar selection
  status         Show config + profile summary
  list           List events  (--digest for day-aware session-start output)
  match          Look up preferences for a title → JSON
  add            Add an event (conflict detection, attendees, prep block)
  delete         Delete an event by title
  reschedule     Move event(s) — single shift/new-time, or bulk by date
  search         Full-text search across past + future events
  free           Find free time slots within work hours
  profile        Show / update user profile (name, hours, style)
  update-prefs   Add or update a preference pattern
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SKILL_DIR   = Path.home() / ".claude/skills/assistant"
CONFIG_FILE = SKILL_DIR / "config.json"
PREFS_FILE  = SKILL_DIR / "preferences.json"
TOKEN_FILE  = SKILL_DIR / "token.json"
SCOPES = ["https://www.googleapis.com/auth/calendar"]

CRED_CANDIDATES = [
    SKILL_DIR / "credentials.json",
    Path.home() / ".openclaw/workspace/skills/proactive-claw/credentials.json",
]

COLOR_MAP = {
    "blue": "1", "green": "2", "purple": "3", "red": "4",
    "yellow": "5", "orange": "6", "turquoise": "7", "gray": "8",
    "bold_blue": "9", "bold_green": "10", "bold_red": "11",
}


# ─── Config helpers ───────────────────────────────────────────────────────────

def find_credentials():
    for p in CRED_CANDIDATES:
        if p.exists():
            return p
    return None

def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}

def save_config(config: dict):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

def load_preferences() -> dict:
    if PREFS_FILE.exists():
        with open(PREFS_FILE) as f:
            return json.load(f)
    return {
        "patterns": [],
        "defaults": {"duration_minutes": 30, "color": "bold_blue", "reminder_minutes": 10},
    }

def save_preferences(prefs: dict):
    with open(PREFS_FILE, "w") as f:
        json.dump(prefs, f, indent=2)

def load_profile() -> dict:
    return load_config().get("profile", {})

def match_preferences(title: str, description: str = "") -> dict:
    prefs = load_preferences()
    text  = (title + " " + description).lower()
    for pattern in prefs.get("patterns", []):
        for keyword in pattern.get("match", []):
            if keyword.lower() in text:
                result = dict(prefs.get("defaults", {}))
                result.update({k: v for k, v in pattern.items() if k != "match"})
                result["matched"] = keyword
                return result
    result = dict(prefs.get("defaults", {}))
    result["matched"] = None
    return result


# ─── Timezone detection ───────────────────────────────────────────────────────

def detect_timezone() -> str:
    try:
        lt = Path("/etc/localtime")
        if lt.is_symlink():
            target = str(lt.resolve())
            if "zoneinfo/" in target:
                return target.split("zoneinfo/", 1)[1]
    except Exception:
        pass
    try:
        local_tz = datetime.now().astimezone().tzinfo
        if hasattr(local_tz, "key"):
            return local_tz.key
    except Exception:
        pass
    return datetime.now().astimezone().strftime("%Z")


# ─── Time parsing ─────────────────────────────────────────────────────────────

def parse_time(time_str: str, reference: datetime = None) -> datetime:
    if reference is None:
        reference = datetime.now().astimezone()
    for fmt in [
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]:
        try:
            dt = datetime.strptime(time_str, fmt)
            return dt.replace(tzinfo=reference.tzinfo)
        except ValueError:
            continue
    try:
        import dateparser
        dt = dateparser.parse(time_str, settings={
            "PREFER_DATES_FROM": "future",
            "RETURN_AS_TIMEZONE_AWARE": True,
            "RELATIVE_BASE": reference.replace(tzinfo=None),
        })
        if dt:
            return dt
    except ImportError:
        pass
    raise ValueError(
        f"Cannot parse time: '{time_str}'.\n"
        "Use ISO 8601 (2026-03-01T15:00) or install dateparser:\n"
        "  pip3 install dateparser"
    )


# ─── Google Calendar service ──────────────────────────────────────────────────

def get_service():
    try:
        from google.oauth2.credentials import Credentials          # noqa
        from google.auth.transport.requests import Request          # noqa
        from google_auth_oauthlib.flow import InstalledAppFlow      # noqa
        from googleapiclient.discovery import build                 # noqa
    except ImportError:
        print("ERROR: Missing Google API libraries.")
        print("Run: pip3 install google-api-python-client google-auth-oauthlib google-auth-httplib2")
        sys.exit(1)

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        if not creds or not creds.valid:
            creds_file = find_credentials()
            if not creds_file:
                print("ERROR: No credentials.json found. Place it at:")
                for p in CRED_CANDIDATES:
                    print(f"  {p}")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
            creds = flow.run_local_server(port=0)

    SKILL_DIR.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def resolve_calendar_id(service, name_or_id: str) -> str:
    if "@" in name_or_id or name_or_id == "primary":
        return name_or_id
    for cal in service.calendarList().list().execute().get("items", []):
        if cal.get("summary", "").lower() == name_or_id.lower():
            return cal["id"]
    return name_or_id

def effective_calendar_id(pref: dict, config: dict, service) -> str:
    cal_name = pref.get("calendar_name")
    if cal_name:
        return resolve_calendar_id(service, cal_name)
    return config.get("calendar_id", "primary")

def check_conflicts(service, calendar_id: str, start_dt: datetime, end_dt: datetime) -> list:
    """Return events that overlap with the given time range."""
    result = service.events().list(
        calendarId=calendar_id,
        timeMin=start_dt.isoformat(),
        timeMax=end_dt.isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=10,
    ).execute()
    return result.get("items", [])


# ─── Description builder ──────────────────────────────────────────────────────

def build_description(user_text: str) -> str:
    lines = [user_text.rstrip()] if user_text.strip() else []
    lines.append("")
    lines.append("─" * 44)
    project    = os.environ.get("PWD") or os.getcwd()
    session_id = os.environ.get("CLAUDE_SESSION_ID", "")
    lines.append(f"📁  {project}")
    if session_id:
        encoded    = project.replace("/", "-")
        transcript = str(Path.home() / f".claude/projects/{encoded}/{session_id}.jsonl")
        lines.append(f"🔗  Session: {session_id}")
        lines.append(f"📄  Transcript: {transcript}")
    lines.append(f"🕐  Added: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    return "\n".join(lines)


# ─── Commands ─────────────────────────────────────────────────────────────────

def cmd_setup(_args):
    print("🗓️  Assistant Calendar — Setup")
    print("=" * 45)

    creds_file = find_credentials()
    if not creds_file:
        print("\nNo credentials.json found.")
        print("Steps:")
        print("  1. https://console.cloud.google.com → new project → Enable 'Google Calendar API'")
        print("  2. Credentials → Create OAuth 2.0 Client ID (Desktop) → Download JSON")
        print(f"  3. Save to: {CRED_CANDIDATES[0]}")
        sys.exit(1)
    print(f"✅ Credentials: {creds_file}\n")

    service = get_service()
    print("✅ Google Calendar authenticated\n")

    tz = detect_timezone()
    print(f"✅ Detected timezone: {tz}")
    tz_override = input("   Press Enter to accept, or type a different IANA timezone: ").strip()
    if tz_override:
        tz = tz_override
    print()

    calendars = service.calendarList().list().execute().get("items", [])
    print("  1. ➕ Create a new 'Assistant' calendar  ← recommended")
    for i, cal in enumerate(calendars, 1):
        marker = " (primary)" if cal.get("primary") else ""
        print(f"  {i+1:2}. {cal['summary']}{marker}")

    try:
        raw = input(f"\nChoose [1-{len(calendars)+1}] (Enter = create new): ").strip()
        idx = int(raw) - 1 if raw else 0
    except (ValueError, KeyboardInterrupt):
        print("\nCancelled.")
        sys.exit(1)

    if idx == 0:
        cal = service.calendars().insert(body={
            "summary": "Assistant",
            "description": "Entries created by Claude Code — your AI assistant",
        }).execute()
        try:
            service.calendarList().patch(calendarId=cal["id"], body={"colorId": "9"}).execute()
        except Exception:
            pass
        calendar_id   = cal["id"]
        calendar_name = "Assistant"
        print("\n✅ Created 'Assistant' calendar")
    elif 1 <= idx <= len(calendars):
        calendar_id   = calendars[idx - 1]["id"]
        calendar_name = calendars[idx - 1]["summary"]
        print(f"\n✅ Using '{calendar_name}'")
    else:
        print("Invalid choice.")
        sys.exit(1)

    config = load_config()
    config.update({
        "calendar_id":   calendar_id,
        "calendar_name": calendar_name,
        "timezone":      tz,
        "setup_at":      datetime.now(timezone.utc).isoformat(),
    })
    save_config(config)
    print(f"💾 Config saved to {CONFIG_FILE}")
    print("\nNext: run 'calendar.py profile --setup' to personalise the assistant.")


def cmd_status(_args):
    config = load_config()
    if not config.get("calendar_id"):
        print("NOT SET UP — run: python3 calendar.py setup")
        sys.exit(1)
    print("✅  Assistant Calendar — ready")
    print(f"   Calendar : {config.get('calendar_name', '?')}  ({config['calendar_id']})")
    print(f"   Timezone : {config.get('timezone', 'UTC')}")
    print(f"   Set up   : {config.get('setup_at', '?')[:10]}")
    profile = config.get("profile", {})
    if profile:
        wh   = profile.get("work_hours", {})
        name = profile.get("preferred_name") or profile.get("name", "")
        print(f"   Profile  : {name}  |  {wh.get('start','09:00')}–{wh.get('end','18:00')}  |  {profile.get('working_style','')}")
    else:
        print("   Profile  : not set — run: calendar.py profile --setup")


def cmd_list(args):
    config = load_config()
    if not config.get("calendar_id"):
        print("NOT SET UP — run: python3 calendar.py setup")
        sys.exit(1)

    # Digest mode: show week on Monday, today otherwise
    digest = getattr(args, "digest", False)
    if digest:
        today_wd = datetime.now().weekday()
        if today_wd == 0:   # Monday
            args.days_back  = 0
            args.days_ahead = 7
            print("📅 Week ahead:\n")
        else:
            args.days_back  = 0
            args.days_ahead = 1

    service = get_service()
    now      = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=args.days_back)).isoformat()
    time_max = (now + timedelta(days=args.days_ahead)).isoformat()

    result = service.events().list(
        calendarId=config["calendar_id"],
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
        maxResults=50,
    ).execute()

    events = result.get("items", [])
    if not events:
        if not digest:
            print(f"No events in the past {args.days_back}d / next {args.days_ahead}d.")
        return

    if not digest:
        print(f"Assistant calendar — past {args.days_back}d / next {args.days_ahead}d  ({config.get('timezone','UTC')})\n")

    for ev in events:
        ev_id  = ev.get("id", "")
        title  = ev.get("summary", "(no title)")
        dt_str = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date", "")
        try:
            dt      = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            display = dt.strftime("%a %b %-d  %H:%M")
            past    = "✓ " if dt < now else "  "
        except Exception:
            display = dt_str
            past    = "  "
        print(f"{past}{display}  {title}")
        if not digest:
            print(f"         id: {ev_id[:16]}")


def cmd_match(args):
    result = match_preferences(args.title, getattr(args, "description", "") or "")
    print(json.dumps(result, indent=2))


def cmd_add(args):
    config = load_config()
    if not config.get("calendar_id"):
        print("ERROR: Not set up. Run: python3 calendar.py setup")
        sys.exit(1)

    service     = get_service()
    pref        = match_preferences(args.title, args.description or "")
    calendar_id = effective_calendar_id(pref, config, service)
    tz_str      = args.timezone or config.get("timezone", "UTC")

    ref = datetime.now().astimezone()
    try:
        start_dt = parse_time(args.start, ref)
        end_dt   = parse_time(args.end,   ref)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S")
    end_iso   = end_dt.strftime("%Y-%m-%dT%H:%M:%S")

    color      = args.color    or pref.get("color", "bold_blue")
    reminder   = args.reminder if args.reminder is not None else pref.get("reminder_minutes", 10)
    recurrence = args.recurrence or pref.get("recurrence", "")
    cal_display = pref.get("calendar_name") or config.get("calendar_name", calendar_id)

    # Work hours warning
    profile = load_profile()
    if profile:
        wh        = profile.get("work_hours", {})
        no_before = profile.get("no_schedule_before", wh.get("start", ""))
        no_after  = profile.get("no_schedule_after",  wh.get("end", ""))
        if no_before:
            lh, lm = map(int, no_before.split(":"))
            if start_dt.hour < lh or (start_dt.hour == lh and start_dt.minute < lm):
                print(f"⚠️  Note: this is before your usual start ({no_before})")
        if no_after:
            lh, lm = map(int, no_after.split(":"))
            if start_dt.hour > lh or (start_dt.hour == lh and start_dt.minute > lm):
                print(f"⚠️  Note: this is after your preferred cutoff ({no_after})")

    # Conflict detection
    conflicts = check_conflicts(service, calendar_id, start_dt, end_dt)
    if conflicts:
        print(f"\n⚠️  Time conflict — {len(conflicts)} existing event(s):")
        for ev in conflicts:
            ev_dt = ev.get("start", {}).get("dateTime", "")[:16]
            print(f"   • {ev.get('summary', '(no title)')}  {ev_dt}")
        if not args.yes:
            try:
                if input("\nSchedule anyway? [y/N]: ").strip().lower() != "y":
                    print("Cancelled.")
                    sys.exit(0)
            except KeyboardInterrupt:
                print("\nCancelled.")
                sys.exit(0)

    # Attendees
    attendees_str = getattr(args, "attendees", "") or ""
    attendees     = [e.strip() for e in attendees_str.split(",") if e.strip()]

    # Prep block
    prep_minutes = getattr(args, "prep_minutes", 0) or 0

    # Confirm preview
    if not args.yes:
        print(f"\n📅 Preview")
        print(f"   Title    : {args.title}")
        print(f"   When     : {start_iso} → {end_iso} ({tz_str})")
        print(f"   Calendar : {cal_display}")
        print(f"   Color    : {color}")
        print(f"   Reminder : {reminder} min before")
        if recurrence:
            print(f"   Repeats  : {recurrence}")
        if attendees:
            print(f"   Invites  : {', '.join(attendees)}  (sends email invitations)")
        if prep_minutes:
            print(f"   Prep     : +{prep_minutes}min prep block added before")
        if pref.get("matched"):
            print(f"   Pref     : matched '{pref['matched']}'")
        print()
        try:
            if input("Add this? [Y/n]: ").strip().lower() == "n":
                print("Cancelled.")
                sys.exit(0)
        except KeyboardInterrupt:
            print("\nCancelled.")
            sys.exit(0)

    event_body = {
        "summary":     args.title,
        "description": build_description(args.description or ""),
        "start":  {"dateTime": start_iso, "timeZone": tz_str},
        "end":    {"dateTime": end_iso,   "timeZone": tz_str},
        "colorId": COLOR_MAP.get(color, "9"),
        "reminders": {
            "useDefault": False,
            "overrides":  [{"method": "popup", "minutes": reminder}],
        },
    }
    if recurrence:
        event_body["recurrence"] = [recurrence] if isinstance(recurrence, str) else recurrence
    if attendees:
        event_body["attendees"] = [{"email": e} for e in attendees]

    result = service.events().insert(calendarId=calendar_id, body=event_body).execute()
    link   = result.get("htmlLink", "")
    print(f"✅ Added: {args.title}")
    print(f"   📅 {start_iso} → {end_iso} ({tz_str})")
    print(f"   📆 {cal_display}")
    if pref.get("matched"):
        print(f"   (used '{pref['matched']}' preference)")
    if attendees:
        print(f"   📧 Invited: {', '.join(attendees)}")
    if link:
        print(f"   🔗 {link}")

    # Auto prep block
    if prep_minutes > 0:
        prep_end   = start_dt
        prep_start = start_dt - timedelta(minutes=prep_minutes)
        prep_body  = {
            "summary":     f"Prep: {args.title}",
            "description": f"Preparation time for: {args.title}",
            "start": {"dateTime": prep_start.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": tz_str},
            "end":   {"dateTime": prep_end.strftime("%Y-%m-%dT%H:%M:%S"),   "timeZone": tz_str},
            "colorId": COLOR_MAP.get("yellow", "5"),
            "reminders": {"useDefault": False, "overrides": []},
        }
        service.events().insert(calendarId=calendar_id, body=prep_body).execute()
        print(f"   + Prep block: {prep_start.strftime('%H:%M')} → {prep_end.strftime('%H:%M')}")


def cmd_delete(args):
    config = load_config()
    if not config.get("calendar_id"):
        print("NOT SET UP"); sys.exit(1)

    service = get_service()
    now     = datetime.now(timezone.utc)

    result = service.events().list(
        calendarId=config["calendar_id"],
        timeMin=(now - timedelta(days=7)).isoformat(),
        timeMax=(now + timedelta(days=90)).isoformat(),
        q=args.title,
        singleEvents=True,
        orderBy="startTime",
        maxResults=5,
    ).execute()

    events = result.get("items", [])
    if not events:
        print(f"No event found matching: '{args.title}'")
        sys.exit(1)

    if len(events) > 1:
        print("Multiple matches:")
        for i, ev in enumerate(events, 1):
            dt = ev.get("start", {}).get("dateTime", "")[:16]
            print(f"  {i}. {ev.get('summary')} — {dt}")
        try:
            event = events[int(input("Choose [1-N]: ").strip()) - 1]
        except (ValueError, IndexError, KeyboardInterrupt):
            print("Cancelled."); sys.exit(1)
    else:
        event = events[0]

    title  = event.get("summary", "")
    dt_str = event.get("start", {}).get("dateTime", "")[:16]
    print(f"Delete: {title} ({dt_str})")

    if not args.yes:
        try:
            if input("Confirm? [Y/n]: ").strip().lower() == "n":
                print("Cancelled."); sys.exit(0)
        except KeyboardInterrupt:
            print("\nCancelled."); sys.exit(0)

    service.events().delete(calendarId=config["calendar_id"], eventId=event["id"]).execute()
    print(f"✅ Deleted: {title}")


def cmd_reschedule(args):
    config = load_config()
    if not config.get("calendar_id"):
        print("NOT SET UP"); sys.exit(1)

    service = get_service()
    now     = datetime.now(timezone.utc)
    ref     = datetime.now().astimezone()

    # ── Bulk mode: move all events on a given date ─────────────────────────
    if args.date:
        try:
            day = parse_time(args.date, ref).replace(hour=0, minute=0, second=0, microsecond=0)
        except ValueError as e:
            print(f"ERROR: {e}"); sys.exit(1)

        day_end = day + timedelta(days=1)
        result  = service.events().list(
            calendarId=config["calendar_id"],
            timeMin=day.isoformat(),
            timeMax=day_end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = result.get("items", [])
        if not events:
            print(f"No events on {day.strftime('%a %b %-d')}.")
            sys.exit(0)

        if not args.shift:
            print("Provide --shift for bulk reschedule (e.g. +1d, +2h, -30m)")
            sys.exit(1)

        m = re.match(r'^([+-]?)(\d+)([hmd])$', args.shift.strip())
        if not m:
            print(f"Invalid shift '{args.shift}'. Use: +2h  +30m  +1d  -1h"); sys.exit(1)
        sign  = -1 if m.group(1) == "-" else 1
        n     = int(m.group(2))
        unit  = m.group(3)
        delta = timedelta(
            hours=n*sign   if unit == "h" else 0,
            minutes=n*sign if unit == "m" else 0,
            days=n*sign    if unit == "d" else 0,
        )

        print(f"Bulk reschedule — {len(events)} event(s) on {day.strftime('%a %b %-d')} by {args.shift}")
        for ev in events:
            print(f"  • {ev.get('summary')} — {ev.get('start',{}).get('dateTime','')[:16]}")

        if not args.yes:
            try:
                if input("\nConfirm? [Y/n]: ").strip().lower() == "n":
                    print("Cancelled."); sys.exit(0)
            except KeyboardInterrupt:
                print("\nCancelled."); sys.exit(0)

        for ev in events:
            old_s  = datetime.fromisoformat(ev["start"]["dateTime"].replace("Z", "+00:00"))
            old_e  = datetime.fromisoformat(ev["end"]["dateTime"].replace("Z", "+00:00"))
            tz_ev  = ev["start"].get("timeZone") or config.get("timezone", "UTC")
            new_s  = old_s + delta
            new_e  = old_e + delta
            service.events().patch(
                calendarId=config["calendar_id"],
                eventId=ev["id"],
                body={
                    "start": {"dateTime": new_s.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": tz_ev},
                    "end":   {"dateTime": new_e.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": tz_ev},
                },
            ).execute()
            print(f"  ✅ {ev.get('summary')} → {new_s.strftime('%a %b %-d %H:%M')}")
        return

    # ── Single event reschedule ─────────────────────────────────────────────
    if not args.title:
        print("Provide --title (single) or --date (bulk)")
        sys.exit(1)

    result = service.events().list(
        calendarId=config["calendar_id"],
        timeMin=(now - timedelta(days=7)).isoformat(),
        timeMax=(now + timedelta(days=30)).isoformat(),
        q=args.title,
        singleEvents=True,
        orderBy="startTime",
        maxResults=5,
    ).execute()

    events = result.get("items", [])
    if not events:
        print(f"No event found matching: '{args.title}'")
        sys.exit(1)

    if len(events) > 1:
        print("Multiple matches:")
        for i, ev in enumerate(events, 1):
            dt = ev.get("start", {}).get("dateTime", "")
            print(f"  {i}. [{ev['id'][:8]}] {ev.get('summary')} — {dt}")
        try:
            event = events[int(input("Choose: ").strip()) - 1]
        except (ValueError, IndexError, KeyboardInterrupt):
            print("Cancelled."); sys.exit(1)
    else:
        event = events[0]

    ev_id        = event["id"]
    title        = event.get("summary", "")
    old_start_str = event["start"].get("dateTime", "")
    old_end_str   = event["end"].get("dateTime", "")
    tz_str        = event["start"].get("timeZone") or config.get("timezone", "UTC")
    old_start     = datetime.fromisoformat(old_start_str.replace("Z", "+00:00"))
    old_end       = datetime.fromisoformat(old_end_str.replace("Z", "+00:00"))
    duration      = old_end - old_start

    if args.shift:
        m = re.match(r'^([+-]?)(\d+)([hmd])$', args.shift.strip())
        if not m:
            print(f"Invalid shift '{args.shift}'. Use: +2h  +30m  +1d  -1h"); sys.exit(1)
        sign  = -1 if m.group(1) == "-" else 1
        n     = int(m.group(2))
        unit  = m.group(3)
        delta = timedelta(
            hours=n*sign   if unit == "h" else 0,
            minutes=n*sign if unit == "m" else 0,
            days=n*sign    if unit == "d" else 0,
        )
        new_start = old_start + delta
        new_end   = new_start + duration
    elif args.new_start:
        new_start = parse_time(args.new_start, ref)
        new_end   = new_start + duration
    else:
        print("Provide --shift (+2h / +30m / +1d) or --new-start 'tomorrow 3pm'")
        sys.exit(1)

    new_start_iso = new_start.strftime("%Y-%m-%dT%H:%M:%S")
    new_end_iso   = new_end.strftime("%Y-%m-%dT%H:%M:%S")

    print(f"Rescheduling: {title}")
    print(f"  From: {old_start_str[:16]}")
    print(f"  To:   {new_start_iso}  ({tz_str})")

    if not args.yes:
        try:
            if input("Confirm? [Y/n]: ").strip().lower() == "n":
                print("Cancelled."); sys.exit(0)
        except KeyboardInterrupt:
            print("\nCancelled."); sys.exit(0)

    service.events().patch(
        calendarId=config["calendar_id"],
        eventId=ev_id,
        body={
            "start": {"dateTime": new_start_iso, "timeZone": tz_str},
            "end":   {"dateTime": new_end_iso,   "timeZone": tz_str},
        },
    ).execute()
    print(f"✅ Rescheduled: {title} → {new_start_iso}")


def cmd_search(args):
    config = load_config()
    if not config.get("calendar_id"):
        print("NOT SET UP"); sys.exit(1)

    service = get_service()
    now     = datetime.now(timezone.utc)

    result = service.events().list(
        calendarId=config["calendar_id"],
        timeMin=(now - timedelta(days=args.days_back)).isoformat(),
        timeMax=(now + timedelta(days=args.days_ahead)).isoformat(),
        q=args.query,
        singleEvents=True,
        orderBy="startTime",
        maxResults=25,
    ).execute()

    events = result.get("items", [])
    if not events:
        print(f"No events found matching: '{args.query}'")
        return

    print(f"Search: '{args.query}' — {len(events)} result(s)\n")
    for ev in events:
        dt_str = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date", "")
        try:
            dt      = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            display = dt.strftime("%a %b %-d  %H:%M")
            past    = "✓ " if dt < now else "  "
        except Exception:
            display = dt_str
            past    = "  "
        print(f"{past}{display}  {ev.get('summary', '(no title)')}")
        desc = ev.get("description", "")
        if desc:
            for line in desc.split("\n"):
                line = line.strip()
                if line and not line.startswith("─"):
                    print(f"         {line[:80]}")
                    break


def cmd_free(args):
    config = load_config()
    if not config.get("calendar_id"):
        print("NOT SET UP"); sys.exit(1)

    service  = get_service()
    profile  = load_profile()
    ref      = datetime.now().astimezone()

    # Resolve date + span
    date_str = (args.date or "today").lower()
    if date_str in ("today", ""):
        base      = ref.replace(hour=0, minute=0, second=0, microsecond=0)
        span_days = 1
    elif date_str == "tomorrow":
        base      = (ref + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        span_days = 1
    elif date_str == "this week":
        base      = (ref - timedelta(days=ref.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        span_days = 5
    elif date_str == "next week":
        base      = (ref - timedelta(days=ref.weekday()) + timedelta(weeks=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        span_days = 5
    else:
        try:
            base      = parse_time(date_str, ref).replace(hour=0, minute=0, second=0, microsecond=0)
            span_days = 1
        except ValueError as e:
            print(f"ERROR: {e}"); sys.exit(1)

    if args.days:
        span_days = args.days

    duration_min = args.duration
    wh           = profile.get("work_hours", {})
    work_start   = wh.get("start", "09:00")
    work_end     = wh.get("end",   "18:00")
    ws_h, ws_m   = map(int, work_start.split(":"))
    we_h, we_m   = map(int, work_end.split(":"))
    work_days    = profile.get("work_days", [0, 1, 2, 3, 4])   # 0=Mon

    print(f"🔍 Free slots ≥ {duration_min}min  |  work hours: {work_start}–{work_end}\n")

    # Collect unique calendar IDs for freebusy query
    cal_ids = list({config["calendar_id"], "primary"})

    found_any = False
    for day_offset in range(span_days):
        day = base + timedelta(days=day_offset)
        if day.weekday() not in work_days:
            continue

        day_start = day.replace(hour=ws_h, minute=ws_m, second=0, microsecond=0)
        day_end   = day.replace(hour=we_h, minute=we_m, second=0, microsecond=0)

        # Use freebusy API — checks ALL queried calendars at once
        fb = service.freebusy().query(body={
            "timeMin": day_start.isoformat(),
            "timeMax": day_end.isoformat(),
            "items":   [{"id": cid} for cid in cal_ids],
        }).execute()

        busy = []
        for cal_data in fb.get("calendars", {}).values():
            for slot in cal_data.get("busy", []):
                try:
                    ev_s = datetime.fromisoformat(slot["start"].replace("Z", "+00:00")).astimezone(day_start.tzinfo)
                    ev_e = datetime.fromisoformat(slot["end"].replace("Z", "+00:00")).astimezone(day_start.tzinfo)
                    busy.append((ev_s, ev_e))
                except Exception:
                    continue

        # Compute free gaps
        slots  = []
        cursor = day_start
        for ev_s, ev_e in sorted(set(busy), key=lambda x: x[0]):
            gap = int((ev_s - cursor).total_seconds() / 60)
            if gap >= duration_min:
                slots.append((cursor, ev_s))
            cursor = max(cursor, ev_e)
        gap = int((day_end - cursor).total_seconds() / 60)
        if gap >= duration_min:
            slots.append((cursor, day_end))

        if slots:
            found_any = True
            print(f"  {day.strftime('%a %b %-d')}:")
            for s, e in slots:
                gap_min = int((e - s).total_seconds() / 60)
                print(f"    {s.strftime('%H:%M')} – {e.strftime('%H:%M')}  ({gap_min}min free)")

    if not found_any:
        print(f"No free slots ≥ {duration_min}min found.")


def cmd_profile(args):
    config  = load_config()
    profile = config.get("profile", {})

    has_flags = any([
        getattr(args, "setup", False),
        getattr(args, "name", None),
        getattr(args, "work_start", None),
        getattr(args, "work_end", None),
        getattr(args, "style", None),
        getattr(args, "no_before", None),
        getattr(args, "no_after", None),
    ])

    if not has_flags:
        if not profile:
            print("No profile set. Run: calendar.py profile --setup")
        else:
            print("👤 Profile:")
            print(json.dumps(profile, indent=2))
        return

    if getattr(args, "setup", False):
        print("👤 Profile Setup")
        print("=" * 40)
        prev_wh  = profile.get("work_hours", {})
        name     = input(f"Name [{profile.get('name','')}]: ").strip() or profile.get("name", "")
        pref_nm  = input(f"Preferred name [{profile.get('preferred_name', name)}]: ").strip() or profile.get("preferred_name", name)
        ws       = input(f"Work start [{prev_wh.get('start','09:00')}]: ").strip() or prev_wh.get("start", "09:00")
        we       = input(f"Work end   [{prev_wh.get('end','18:00')}]: ").strip()   or prev_wh.get("end",   "18:00")
        style    = input(f"Style (morning/evening/flexible) [{profile.get('working_style','flexible')}]: ").strip() or profile.get("working_style", "flexible")
        no_bef   = input(f"Don't schedule before [{profile.get('no_schedule_before', ws)}]: ").strip() or profile.get("no_schedule_before", ws)
        no_aft   = input(f"Don't schedule after  [{profile.get('no_schedule_after','20:00')}]: ").strip() or profile.get("no_schedule_after", "20:00")

        profile.update({
            "name":               name,
            "preferred_name":     pref_nm,
            "work_hours":         {"start": ws, "end": we},
            "working_style":      style,
            "no_schedule_before": no_bef,
            "no_schedule_after":  no_aft,
            "work_days":          profile.get("work_days", [0, 1, 2, 3, 4]),
        })
        config["profile"] = profile
        save_config(config)
        print(f"\n✅ Profile saved.")
        return

    # Flag-based updates
    if getattr(args, "name",       None): profile["name"]         = args.name
    if getattr(args, "work_start", None): profile.setdefault("work_hours", {})["start"] = args.work_start
    if getattr(args, "work_end",   None): profile.setdefault("work_hours", {})["end"]   = args.work_end
    if getattr(args, "style",      None): profile["working_style"]      = args.style
    if getattr(args, "no_before",  None): profile["no_schedule_before"] = args.no_before
    if getattr(args, "no_after",   None): profile["no_schedule_after"]  = args.no_after

    config["profile"] = profile
    save_config(config)
    print("✅ Profile updated:")
    print(json.dumps(profile, indent=2))


def cmd_update_prefs(args):
    prefs    = load_preferences()
    patterns = prefs.get("patterns", [])

    existing_idx = None
    for i, p in enumerate(patterns):
        if args.match.lower() in [k.lower() for k in p.get("match", [])]:
            existing_idx = i
            break

    if existing_idx is not None:
        pattern = patterns[existing_idx]
        print(f"Updating existing rule for '{args.match}':")
    else:
        pattern = {"match": [args.match]}
        print(f"Creating new rule for '{args.match}':")

    if args.duration      is not None: pattern["duration_minutes"] = args.duration
    if args.color:                     pattern["color"]             = args.color
    if args.reminder      is not None: pattern["reminder_minutes"]  = args.reminder
    if args.calendar_name:             pattern["calendar_name"]     = args.calendar_name
    if args.recurrence:                pattern["recurrence"]        = args.recurrence

    print(json.dumps(pattern, indent=2))

    if existing_idx is not None:
        patterns[existing_idx] = pattern
    else:
        patterns.append(pattern)

    prefs["patterns"] = patterns
    save_preferences(prefs)
    print(f"✅ Saved to {PREFS_FILE}")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Assistant Calendar — Claude Code skill backend")
    sub    = parser.add_subparsers(dest="command")

    sub.add_parser("setup",  help="OAuth + timezone + calendar setup")
    sub.add_parser("status", help="Show config + profile summary")

    li = sub.add_parser("list", help="List events")
    li.add_argument("--days-back",  type=int, default=3)
    li.add_argument("--days-ahead", type=int, default=7)
    li.add_argument("--digest", action="store_true", help="Day-aware: week on Monday, today otherwise")

    m = sub.add_parser("match", help="Match preferences for a title → JSON")
    m.add_argument("--title",       required=True)
    m.add_argument("--description", default="")

    p = sub.add_parser("add", help="Add a calendar event")
    p.add_argument("--title",        required=True)
    p.add_argument("--start",        required=True)
    p.add_argument("--end",          required=True)
    p.add_argument("--description",  default="")
    p.add_argument("--timezone",     default="")
    p.add_argument("--color",        default="")
    p.add_argument("--reminder",     type=int, default=None)
    p.add_argument("--recurrence",   default="", help="RRULE string")
    p.add_argument("--attendees",    default="", help="Comma-separated emails")
    p.add_argument("--prep-minutes", type=int, default=0, dest="prep_minutes",
                   help="Auto-add a prep block N min before the event")
    p.add_argument("--yes", "-y",    action="store_true")

    de = sub.add_parser("delete", help="Delete an event by title")
    de.add_argument("--title",    required=True)
    de.add_argument("--yes", "-y", action="store_true")

    r = sub.add_parser("reschedule", help="Move event(s)")
    r.add_argument("--title",     default="", help="Title keyword (single event)")
    r.add_argument("--date",      default="", help="Date for bulk move (e.g. 'Tuesday', '2026-03-10')")
    r.add_argument("--shift",     default="", help="+2h  +30m  +1d  -1h")
    r.add_argument("--new-start", default="", dest="new_start", help="New start (single only)")
    r.add_argument("--yes", "-y", action="store_true")

    se = sub.add_parser("search", help="Search events by keyword")
    se.add_argument("query")
    se.add_argument("--days-back",  type=int, default=90)
    se.add_argument("--days-ahead", type=int, default=90)

    fr = sub.add_parser("free", help="Find free time slots within work hours")
    fr.add_argument("--date",     default="today",
                    help="today|tomorrow|this week|next week|YYYY-MM-DD")
    fr.add_argument("--duration", type=int, default=30,
                    help="Minimum slot length in minutes (default 30)")
    fr.add_argument("--days",     type=int, default=0,
                    help="Override number of days to scan")

    pr = sub.add_parser("profile", help="Show or update user profile")
    pr.add_argument("--setup",      action="store_true", help="Interactive setup wizard")
    pr.add_argument("--name",       default=None)
    pr.add_argument("--work-start", default=None, dest="work_start", help="HH:MM")
    pr.add_argument("--work-end",   default=None, dest="work_end",   help="HH:MM")
    pr.add_argument("--style",      default=None, help="morning|evening|flexible")
    pr.add_argument("--no-before",  default=None, dest="no_before",  help="Don't schedule before HH:MM")
    pr.add_argument("--no-after",   default=None, dest="no_after",   help="Don't schedule after HH:MM")

    up = sub.add_parser("update-prefs", help="Add or update a preference rule")
    up.add_argument("--match",         required=True)
    up.add_argument("--duration",      type=int, default=None)
    up.add_argument("--color",         default="")
    up.add_argument("--reminder",      type=int, default=None)
    up.add_argument("--calendar-name", default="", dest="calendar_name")
    up.add_argument("--recurrence",    default="")

    args = parser.parse_args()
    dispatch = {
        "setup":        cmd_setup,
        "status":       cmd_status,
        "list":         cmd_list,
        "match":        cmd_match,
        "add":          cmd_add,
        "delete":       cmd_delete,
        "reschedule":   cmd_reschedule,
        "search":       cmd_search,
        "free":         cmd_free,
        "profile":      cmd_profile,
        "update-prefs": cmd_update_prefs,
    }
    fn = dispatch.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
