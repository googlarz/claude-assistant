#!/usr/bin/env python3
"""
Assistant Tasks — lightweight local task list

Commands:
  add       Add a new task
  list      List all pending tasks (sorted by priority)
  today     Tasks due today + all high-priority tasks
  week      Tasks due in the next 7 days
  overdue   Tasks past their due date
  complete  Mark a task complete by ID prefix or title
  delete    Remove a task permanently
  category  List tasks grouped by category (or filter to one)
  summary   One-line counts: N pending, N overdue, N due today
"""

import argparse
import json
import sys
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path

SKILL_DIR  = Path.home() / ".claude/skills/assistant"
TASKS_FILE = SKILL_DIR / "tasks.json"

PRIORITY_ICON = {"high": "🔴", "medium": "🟡", "low": "🟢"}
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


# ─── Storage ──────────────────────────────────────────────────────────────────

def load_tasks() -> list:
    if TASKS_FILE.exists():
        with open(TASKS_FILE) as f:
            return json.load(f)
    return []

def save_tasks(tasks: list):
    SKILL_DIR.mkdir(parents=True, exist_ok=True)
    with open(TASKS_FILE, "w") as f:
        json.dump(tasks, f, indent=2)

def short_id(task_id: str) -> str:
    return task_id[:8]


# ─── Formatting ───────────────────────────────────────────────────────────────

def fmt_task(t: dict, num: int = None, show_id: bool = True) -> str:
    pri  = PRIORITY_ICON.get(t.get("priority", "medium"), "⚪")
    due  = t.get("due_date", "")
    cat  = t.get("category", "")

    # Overdue marker
    overdue_str = ""
    if due:
        try:
            days_left = (date.fromisoformat(due) - date.today()).days
            if days_left < 0:
                overdue_str = f"  ⚠️ overdue {abs(days_left)}d"
            elif days_left == 0:
                overdue_str = "  📌 today"
            elif days_left == 1:
                overdue_str = "  ⏰ tomorrow"
            else:
                overdue_str = f"  due {due}"
        except ValueError:
            overdue_str = f"  due {due}"

    cat_str  = f"  [{cat}]" if cat else ""
    id_str   = f"  ({short_id(t['id'])})" if show_id else ""
    num_str  = f"  {num:2}. " if num is not None else "      "

    return f"{num_str}{pri} {t['title']}{overdue_str}{cat_str}{id_str}"


def find_tasks(all_tasks: list, query: str, pending_only: bool = True) -> list:
    """Find tasks by ID prefix or title substring."""
    pool = [t for t in all_tasks if not t.get("completed")] if pending_only else all_tasks
    return [
        t for t in pool
        if t["id"].startswith(query) or query.lower() in t["title"].lower()
    ]


# ─── Commands ─────────────────────────────────────────────────────────────────

def cmd_add(args):
    tasks = load_tasks()
    task  = {
        "id":           str(uuid.uuid4()),
        "title":        args.title,
        "priority":     args.priority or "medium",
        "category":     args.category or "",
        "due_date":     args.due or "",
        "notes":        args.notes or "",
        "created_at":   datetime.now().isoformat(),
        "completed":    False,
        "completed_at": None,
    }
    tasks.append(task)
    save_tasks(tasks)
    due_str = f"  due {task['due_date']}" if task["due_date"] else ""
    print(f"✅ Added: {PRIORITY_ICON.get(task['priority'],'⚪')} {task['title']}{due_str}  ({short_id(task['id'])})")


def cmd_list(args):
    tasks   = load_tasks()
    pending = [t for t in tasks if not t.get("completed")]
    if not pending:
        print("No pending tasks. 🎉")
        return
    pending.sort(key=lambda t: (
        PRIORITY_ORDER.get(t.get("priority", "medium"), 1),
        t.get("due_date") or "zzz",
    ))
    print(f"Tasks — {len(pending)} pending\n")
    for i, t in enumerate(pending, 1):
        print(fmt_task(t, num=i))
    if args.completed:
        done = [t for t in tasks if t.get("completed")]
        if done:
            print(f"\n  ✓ Completed ({len(done)}):")
            for t in done[-10:]:
                print(f"      ✓ {t['title']}  ({short_id(t['id'])})")


def cmd_today(args):
    tasks     = load_tasks()
    today_str = date.today().isoformat()
    due_today = [t for t in tasks if not t.get("completed") and t.get("due_date") == today_str]
    high_nodp = [t for t in tasks if not t.get("completed") and not t.get("due_date") and t.get("priority") == "high"]

    if not due_today and not high_nodp:
        print("No tasks for today.")
        return

    if due_today:
        print(f"📌 Due today ({len(due_today)}):")
        for i, t in enumerate(due_today, 1):
            print(fmt_task(t, num=i))

    if high_nodp:
        print(f"\n🔴 High priority — no due date ({len(high_nodp)}):")
        for t in high_nodp:
            print(fmt_task(t))


def cmd_week(args):
    tasks    = load_tasks()
    today    = date.today()
    week_end = today + timedelta(days=7)
    this_week = [
        t for t in tasks
        if not t.get("completed")
        and t.get("due_date")
        and today <= date.fromisoformat(t["due_date"]) <= week_end
    ]
    if not this_week:
        print("No tasks due this week.")
        return
    this_week.sort(key=lambda t: t["due_date"])
    print(f"📅 Due this week — {len(this_week)} task(s)\n")
    for i, t in enumerate(this_week, 1):
        print(fmt_task(t, num=i))


def cmd_overdue(args):
    tasks   = load_tasks()
    today   = date.today()
    overdue = [
        t for t in tasks
        if not t.get("completed")
        and t.get("due_date")
        and date.fromisoformat(t["due_date"]) < today
    ]
    if not overdue:
        print("No overdue tasks. ✅")
        return
    overdue.sort(key=lambda t: t["due_date"])
    print(f"⚠️  Overdue — {len(overdue)} task(s)\n")
    for i, t in enumerate(overdue, 1):
        print(fmt_task(t, num=i))


def cmd_complete(args):
    tasks   = load_tasks()
    matches = find_tasks(tasks, args.task, pending_only=True)

    if not matches:
        print(f"No pending task matching: '{args.task}'")
        sys.exit(1)

    if len(matches) > 1:
        print("Multiple matches:")
        for i, t in enumerate(matches, 1):
            print(f"  {i}. {t['title']}  ({short_id(t['id'])})")
        try:
            task = matches[int(input("Choose: ").strip()) - 1]
        except (ValueError, IndexError, KeyboardInterrupt):
            print("Cancelled."); sys.exit(1)
    else:
        task = matches[0]

    task["completed"]    = True
    task["completed_at"] = datetime.now().isoformat()
    save_tasks(tasks)
    print(f"✅ Completed: {task['title']}")


def cmd_delete(args):
    tasks   = load_tasks()
    matches = find_tasks(tasks, args.task, pending_only=False)

    if not matches:
        print(f"No task matching: '{args.task}'")
        sys.exit(1)

    if len(matches) > 1:
        print("Multiple matches:")
        for i, t in enumerate(matches, 1):
            print(f"  {i}. {t['title']}  ({short_id(t['id'])})")
        try:
            task = matches[int(input("Choose: ").strip()) - 1]
        except (ValueError, IndexError, KeyboardInterrupt):
            print("Cancelled."); sys.exit(1)
    else:
        task = matches[0]

    print(f"Delete: {task['title']}")
    try:
        if input("Confirm? [Y/n]: ").strip().lower() == "n":
            print("Cancelled."); sys.exit(0)
    except KeyboardInterrupt:
        print("\nCancelled."); sys.exit(0)

    tasks.remove(task)
    save_tasks(tasks)
    print(f"✅ Deleted: {task['title']}")


def cmd_category(args):
    tasks   = load_tasks()
    pending = [t for t in tasks if not t.get("completed")]

    if args.name:
        pending = [t for t in pending if (t.get("category") or "").lower() == args.name.lower()]

    if not pending:
        label = f"in '{args.name}'" if args.name else ""
        print(f"No pending tasks {label}.".strip())
        return

    # Group
    groups: dict = {}
    for t in pending:
        key = t.get("category") or "uncategorized"
        groups.setdefault(key, []).append(t)

    for cat, items in sorted(groups.items()):
        items.sort(key=lambda t: (PRIORITY_ORDER.get(t.get("priority","medium"),1), t.get("due_date") or "zzz"))
        print(f"\n  {cat.upper()}  ({len(items)})")
        for t in items:
            print(fmt_task(t))


def cmd_summary(_args):
    tasks   = load_tasks()
    today   = date.today()
    pending = [t for t in tasks if not t.get("completed")]
    overdue = [t for t in pending if t.get("due_date") and date.fromisoformat(t["due_date"]) < today]
    due_today = [t for t in pending if t.get("due_date") == today.isoformat()]
    high    = [t for t in pending if t.get("priority") == "high"]

    parts = [f"{len(pending)} pending"]
    if overdue:
        parts.append(f"⚠️ {len(overdue)} overdue")
    if due_today:
        parts.append(f"📌 {len(due_today)} due today")
    if high:
        parts.append(f"🔴 {len(high)} high-priority")
    print("Tasks: " + "  |  ".join(parts))


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Assistant Tasks — local task list")
    sub    = parser.add_subparsers(dest="command")

    a = sub.add_parser("add", help="Add a new task")
    a.add_argument("title")
    a.add_argument("--priority", "-p", choices=["high", "medium", "low"], default="medium")
    a.add_argument("--due",      "-d", default="", help="Due date YYYY-MM-DD")
    a.add_argument("--category", "-c", default="", help="e.g. work, personal, health")
    a.add_argument("--notes",    "-n", default="")

    li = sub.add_parser("list", help="List all pending tasks")
    li.add_argument("--completed", action="store_true", help="Also show last 10 completed")

    sub.add_parser("today",   help="Due today + high-priority tasks")
    sub.add_parser("week",    help="Due in the next 7 days")
    sub.add_parser("overdue", help="Past due date")

    co = sub.add_parser("complete", help="Mark a task complete")
    co.add_argument("task", help="ID prefix or title substring")

    de = sub.add_parser("delete", help="Delete a task")
    de.add_argument("task", help="ID prefix or title substring")

    cat = sub.add_parser("category", help="List tasks by category")
    cat.add_argument("name", nargs="?", default="", help="Filter to this category")

    sub.add_parser("summary", help="One-line counts")

    args = parser.parse_args()
    dispatch = {
        "add":      cmd_add,
        "list":     cmd_list,
        "today":    cmd_today,
        "week":     cmd_week,
        "overdue":  cmd_overdue,
        "complete": cmd_complete,
        "delete":   cmd_delete,
        "category": cmd_category,
        "summary":  cmd_summary,
    }
    fn = dispatch.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
