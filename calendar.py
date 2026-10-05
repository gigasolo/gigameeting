#!/usr/bin/env python3
"""Today's and tomorrow's meetings, and recent recordings, for the GigaMeeting card.

`day` reads HEY's day view for today and tomorrow. The card gets titles and
clock times. The join link, invite text, and people stay in a private cache
for Prep. If HEY cannot be reached, `day` falls back to OmaCal for those two
days. That spare list has no Prep.

`recent` lists recording folders. The card gets a title, a date, and which
documents exist. Paths stay here. `audio` prints one recording path for the
card to play, and only if that file stays inside the meetings folder.
`open-recent` opens the transcript or the insights note the same way, and
returns without waiting for the app that shows it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

def vault_from_obsidian_config(data: object) -> Path | None:
    """The vault Obsidian has open, or the only vault it knows."""
    vaults = data.get("vaults") if isinstance(data, dict) else None
    if not isinstance(vaults, dict):
        return None
    opened: list[str] = []
    known: list[str] = []
    for item in vaults.values():
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if not isinstance(path, str) or not path.startswith("/") or "\x00" in path:
            continue
        known.append(path)
        if item.get("open") is True:
            opened.append(path)
    chosen = opened[0] if len(opened) == 1 else known[0] if len(known) == 1 else ""
    return Path(chosen) if chosen else None


def default_vault() -> Path:
    override = os.environ.get("OBSIDIAN_VAULT")
    if override:
        return Path(os.path.expanduser(override))
    config = Path.home() / ".config" / "obsidian" / "obsidian.json"
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        data = {}
    return vault_from_obsidian_config(data) or Path.home() / "Documents" / "Obsidian"


VAULT = default_vault()
FOLDER = os.environ.get("OBSIDIAN_FOLDER", "Meetings")
MEETINGS = Path(os.path.expanduser(os.environ.get("MEETINGS_ROOT", "~/Documents/Meetings")))
STATE = Path(
    os.path.expanduser(
        os.environ.get(
            "GIGAMEETING_STATE",
            "~/.local/state/omarchy/gigameeting-day.json",
        )
    )
)
MAX_EVENTS = 8
MAX_RECENT = 6
AUDIO_SUFFIXES = {".ogg", ".opus", ".mp3", ".wav", ".m4a", ".flac"}
OPEN_WAIT = 3
ASK_TIMEOUT = 120
ILLEGAL = re.compile(r'[\\/:*?"<>|]')
TAG = re.compile(r"<[^>]+>")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EVENT_RE = re.compile(r'(?m)^event: "((?:\\.|[^"\\])*)"\s*$')
DATE_LINE_RE = re.compile(r"(?m)^date: (\d{4}-\d{2}-\d{2})\s*$")
HEADINGS = (
    "## Summary",
    "## Insights",
    "## Ideas",
    "## Actions",
    "## Open questions",
    "## What this is",
    "## Last time",
    "## Still open",
    "## Worth raising",
)
BRIEF_PROMPT = """Write a short brief for someone about to walk into this meeting.
Markdown only, no preamble. Use only the invite and the past notes below.
Do not invent people, decisions, owners, or deadlines.

Use exactly these headings, in this order:
## What this is
## Last time
## Still open
## Worth raising

What this is is one or two sentences from the invite.

Last time is at most two sentences for each past meeting. End that text with the wiki link from the note's Link line, copied exactly. Prefer the Insights link, and include the transcript link on the same line when that meeting has one. Do not quote dialogue. Do not paste headings, summaries, or an earlier brief.

Still open is one sentence, with that same Insights link. If nothing was left open, write "None yet."

Worth raising is one sentence, or "None yet."

If the invite has no description, say so under What this is.
If there are no past notes, say this looks like the first one, and write "None yet." under Last time and Still open.
If nobody else is listed, keep the brief to the block itself and any past notes. Do not invent attendees.
"""


def fail(message: str) -> None:
    print(f"failed: {message}")
    raise SystemExit(1)


def plain(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = TAG.sub(" ", value)
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def join_url(value: object) -> str:
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value[:2000]
    if isinstance(value, dict):
        for key in ("url", "href"):
            url = value.get(key)
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                return url[:2000]
    return ""


def epoch_ms(stamp: str) -> int | None:
    if "T" not in stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        return None
    return int(when.timestamp() * 1000)


def clock(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).astimezone().strftime("%H:%M")


def local_day(offset: int = 0) -> str:
    return (datetime.now().astimezone().date() + timedelta(days=offset)).isoformat()


def local_today() -> str:
    return local_day(0)


def people_of(row: dict) -> list[dict]:
    raw = row.get("attendances")
    if not isinstance(raw, list):
        return []
    people = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        email = item.get("email_address") if isinstance(item.get("email_address"), str) else ""
        name = item.get("name") if isinstance(item.get("name"), str) else ""
        status = item.get("status") if isinstance(item.get("status"), str) else ""
        email = email.strip()
        name = plain(name, 80)
        status = plain(status, 40)
        if email and not EMAIL.match(email):
            email = ""
        if not email and not name:
            continue
        people.append({"name": name, "email": email[:120], "status": status})
        if len(people) >= 24:
            break
    return people


def normalize_hey(rows: list, now_ms: float, day: str) -> list[dict]:
    events = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("all_day") is True:
            continue
        title = plain(row.get("title"), 200)
        start_raw = row.get("starts_at")
        end_raw = row.get("ends_at")
        event_id = row.get("id")
        if not title or not isinstance(start_raw, str) or not isinstance(event_id, (str, int)):
            continue
        event_id = str(event_id)
        if not event_id or any(char in event_id for char in "\n\r\x00") or len(event_id) > 80:
            continue
        if event_id in seen:
            continue
        start = epoch_ms(start_raw)
        end = epoch_ms(end_raw) if isinstance(end_raw, str) else None
        if start is None or end is None or end <= now_ms:
            continue
        seen.add(event_id)
        events.append(
            {
                "id": event_id,
                "title": title,
                "when": f"{clock(start)}–{clock(end)}",
                "start": start,
                "end": end,
                "date": day,
                "url": join_url(row.get("join_link")),
                "summary": plain(row.get("summary"), 500),
                "description": plain(row.get("description"), 4000),
                "people": people_of(row),
            }
        )
    events.sort(key=lambda item: item["start"])
    return events[:MAX_EVENTS]


def hey_rows(day: str) -> list | None:
    try:
        out = subprocess.run(
            ["hey", "event", "day", day, "--quiet", "--json"],
            capture_output=True,
            text=True,
            timeout=12,
            env={**os.environ, "HEY_NONINTERACTIVE": "1"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    try:
        payload = json.loads(out.stdout)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    return None


def clock_range(start: object, end: object) -> str:
    begin = ""
    finish = ""
    if isinstance(start, str) and "T" in start:
        begin = start.split("T", 1)[1][:5]
    if isinstance(end, str) and "T" in end:
        finish = end.split("T", 1)[1][:5]
    if len(begin) == 5 and begin[2] == ":" and len(finish) == 5 and finish[2] == ":":
        return f"{begin}–{finish}"
    return ""


def local_date_of_ms(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000).astimezone().strftime("%Y-%m-%d")


def omacal_events(now_ms: float | None = None) -> list[dict]:
    try:
        out = subprocess.run(
            ["omacal", "agenda", "--days", "2", "--json"],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0 or not out.stdout.strip():
        return []
    try:
        payload = json.loads(out.stdout)
    except json.JSONDecodeError:
        return []
    rows = payload.get("data") if isinstance(payload, dict) and payload.get("ok") else None
    if not isinstance(rows, list):
        return []
    now = time.time() * 1000 if now_ms is None else now_ms
    today, tomorrow = local_day(0), local_day(1)
    kept = []
    for row in rows:
        if not isinstance(row, dict) or row.get("allDay"):
            continue
        title = plain(row.get("title"), 200)
        start, end = row.get("startMs"), row.get("endMs")
        if not title or isinstance(start, bool) or isinstance(end, bool):
            continue
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            continue
        if end <= now:
            continue
        day = local_date_of_ms(start)
        if day not in (today, tomorrow):
            continue
        url = join_url(row.get("conference"))
        kept.append(
            {
                "id": "",
                "title": title,
                "when": clock_range(row.get("start"), row.get("end")),
                "start": start,
                "end": end,
                "date": day,
                "hasUrl": bool(url),
                "url": url,
                "brief": "",
            }
        )
    kept.sort(key=lambda item: item["start"])
    counts = {today: 0, tomorrow: 0}
    capped = []
    for item in kept:
        if counts[item["date"]] >= MAX_EVENTS:
            continue
        counts[item["date"]] += 1
        capped.append(item)
    return capped


def write_cache(today: str, tomorrow: str, events: list[dict]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps({"date": today, "through": tomorrow, "events": events}, ensure_ascii=False)
    temporary = STATE.with_suffix(".json.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, blob.encode())
    finally:
        os.close(fd)
    os.chmod(temporary, 0o600)
    os.replace(temporary, STATE)
    os.chmod(STATE, 0o600)


def read_cache() -> list[dict]:
    try:
        payload = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    if payload.get("date") != local_day(0) or payload.get("through") != local_day(1):
        return []
    events = payload.get("events")
    return events if isinstance(events, list) else []


def card_event(event: dict, briefs: dict[tuple[str, str], str]) -> dict:
    day = event["date"]
    return {
        "id": f"{event['id']}@{day}",
        "title": event["title"],
        "when": event["when"],
        "start": event["start"],
        "end": event["end"],
        "date": day,
        "hasUrl": bool(event.get("url")),
        "brief": briefs.get((str(event["id"]), day), ""),
    }


def cmd_day() -> None:
    today = local_day(0)
    rows = hey_rows(today)
    if rows is None:
        print(json.dumps({"source": "omacal", "events": omacal_events()}, ensure_ascii=False))
        return
    tomorrow = local_day(1)
    more = hey_rows(tomorrow)
    now_ms = time.time() * 1000
    events = normalize_hey(rows, now_ms, today)
    if more is not None:
        events.extend(normalize_hey(more, now_ms, tomorrow))
    try:
        write_cache(today, tomorrow, events)
    except OSError:
        events = [{**event, "url": ""} for event in events]
    briefs = prep_index()
    print(json.dumps({
        "source": "hey",
        "today": today,
        "tomorrow": tomorrow,
        "events": [card_event(event, briefs) for event in events],
    }, ensure_ascii=False))


def cmd_agenda() -> None:
    print(json.dumps({"events": omacal_events()}, ensure_ascii=False))


def valid_day(day: str) -> bool:
    if not DATE_RE.match(day):
        return False
    year_s, month_s, day_s = day.split("-")
    year, month, day_n = int(year_s), int(month_s), int(day_s)
    if month < 1 or month > 12 or day_n < 1:
        return False
    if month in (4, 6, 9, 11):
        return day_n <= 30
    if month == 2:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        return day_n <= (29 if leap else 28)
    return day_n <= 31


def split_key(value: str) -> tuple[str, str] | None:
    if not isinstance(value, str) or value.count("@") != 1:
        return None
    hey_id, day = value.split("@", 1)
    if not hey_id or len(hey_id) > 80 or any(char in hey_id for char in "\n\r\x00"):
        return None
    if not valid_day(day):
        return None
    return hey_id, day


def event_by_id(key: str) -> dict | None:
    parsed = split_key(key)
    if parsed is None:
        return None
    hey_id, day = parsed
    for event in read_cache():
        if not isinstance(event, dict):
            continue
        if str(event.get("id")) == hey_id and event.get("date") == day:
            return event
    return None


def cmd_open_event(event_id: str) -> None:
    event = event_by_id(event_id)
    url = join_url(event.get("url")) if event else ""
    if not url:
        fail("not a meeting link")
    if not launch(url):
        fail("could not open the meeting link")
    print("opened")


def yaml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def safe_title(title: str) -> str:
    cleaned = ILLEGAL.sub("-", title).strip(" .")
    return cleaned[:80] or "Meeting"


def vault_file(path: Path) -> Path | None:
    try:
        resolved = path.resolve(strict=True)
        base = VAULT.resolve(strict=True)
    except OSError:
        return None
    if resolved == base or base not in resolved.parents:
        return None
    if resolved.suffix.lower() != ".md" or not resolved.is_file():
        return None
    return resolved


def section(text: str, heading: str) -> str:
    start = text.find(heading)
    if start == -1:
        return ""
    rest = text[start + len(heading):]
    nxt = rest.find("\n## ")
    body = rest if nxt == -1 else rest[:nxt]
    return (heading + "\n" + body.strip()).strip()


def without_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:]
    return text


def plain_body(text: str, heading: str) -> str:
    chunk = section(text, heading)
    if not chunk:
        return ""
    return re.sub(r"\s+", " ", chunk[len(heading):]).strip()


def one_sentence(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", text)
    if not text:
        return ""
    stop = len(text)
    for mark in (". ", "? ", "! "):
        at = text.find(mark)
        if at != -1:
            stop = min(stop, at + 1)
    sentence = text[:stop].strip()
    if len(sentence) <= limit:
        return sentence
    cut = sentence[:limit].rsplit(" ", 1)[0].rstrip(".,;:")
    return (cut or sentence[:limit]) + "…"


def excerpt(text: str) -> str:
    text = without_frontmatter(text)
    cut = text.find("## Transcript")
    if cut != -1:
        text = text[:cut]
    parts: list[str] = []
    for heading, limit in (
        ("## Summary", 400),
        ("## Open questions", 240),
        ("## Actions", 200),
        ("## Insights", 240),
    ):
        body = plain_body(text, heading)
        if body:
            parts.append(heading + "\n" + one_sentence(body, limit))
    blob = "\n\n".join(parts).strip()
    if not blob:
        if cut != -1:
            return "Transcript only. What was said is in the linked note."
        blob = re.sub(r"\s+", " ", text).strip()[:400]
    return blob[:1200]


def wiki_link(path: Path) -> str:
    """Obsidian wiki link for a vault note. note_link() is the card's obsidian:// URL."""
    try:
        rel = path.resolve().relative_to(VAULT.resolve()).with_suffix("")
    except (OSError, ValueError):
        rel = path.with_suffix("")
    return "[[" + rel.as_posix() + "]]"


def title_of(path: Path) -> str:
    stem = path.stem
    if stem.endswith(" — Insights"):
        stem = stem[: -len(" — Insights")]
    if len(stem) > 11 and stem[10] == " " and stem[4] == "-" and stem[:4].isdigit():
        stem = stem[11:]
    return stem.strip()


def note_day(path: Path) -> str:
    stem = path.stem
    if len(stem) < 10 or stem[4] != "-" or stem[7] != "-":
        return ""
    day = stem[:10]
    if not (day[:4].isdigit() and day[5:7].isdigit() and day[8:10].isdigit()):
        return ""
    return day


TITLE_STOP = {
    "a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "at", "with",
    "meeting", "discussion",
}


def title_tokens(title: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]+", title.casefold())
        if word not in TITLE_STOP and len(word) >= 2
    }


def titles_related(left: str, right: str) -> bool:
    """Same meeting, a one-character title typo, or a renamed series such as an added topic."""
    if titles_near(left, right):
        return True
    left_tokens = title_tokens(left)
    right_tokens = title_tokens(right)
    if len(left_tokens) < 2 or len(right_tokens) < 2:
        return False
    shared = left_tokens & right_tokens
    if len(shared) < 2:
        return False
    return len(shared) / min(len(left_tokens), len(right_tokens)) >= 0.5


def header_people(text: str) -> set[str]:
    """First names from [[Name]] links in the note header. Insight notes store speakers this way."""
    head = text.split("\n## ", 1)[0]
    found: set[str] = set()
    for raw in re.findall(r"\[\[([^\]|#]+)\]\]", head):
        name = raw.strip()
        if not name or "/" in name or len(name) > 40:
            continue
        token = re.split(r"[\s.]+", name)[0].casefold()
        if len(token) >= 3 and token.isalpha():
            found.add(token)
    return found


def attendee_keys(event: dict) -> set[str]:
    found: set[str] = set()
    for person in event.get("people") or []:
        if not isinstance(person, dict):
            continue
        name = person.get("name") if isinstance(person.get("name"), str) else ""
        email = person.get("email") if isinstance(person.get("email"), str) else ""
        if name and "@" not in name:
            token = re.split(r"[\s.]+", name.strip())[0].casefold()
            if len(token) >= 3 and token.isalpha():
                found.add(token)
        if "@" in email:
            token = re.split(r"[.\-_]", email.split("@", 1)[0])[0].casefold()
            if len(token) >= 3 and token.isalpha():
                found.add(token)
    return found


def invite_prose(event: dict) -> str:
    """Invite text with the dial-in and join link removed. A repeated title is not a description."""
    description = event.get("description") or ""
    cleaned = re.sub(
        r"(?i)\b(?:join with google meet:|or dial:|more phone numbers:|learn more about meet at:)"
        r"|pin:\s*\d+#?|\(us\)\s*\+[\d][\d\-\s]{6,}\d|https?://\S+",
        " ",
        description,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,-")
    summary = (event.get("summary") or "").strip()
    title = (event.get("title") or "").strip()
    if summary.casefold() == title.casefold():
        summary = ""
    if cleaned and summary and summary.casefold() not in cleaned.casefold():
        return f"{summary}\n\n{cleaned}"
    return cleaned or summary


def titles_near(left: str, right: str) -> bool:
    """True when two titles match, or differ by one inserted, deleted, or replaced character."""
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) > len(right):
        left, right = right, left
    edits = 0
    i = 0
    j = 0
    while i < len(left) and j < len(right):
        if left[i] == right[j]:
            i += 1
            j += 1
            continue
        edits += 1
        if edits > 1:
            return False
        if len(left) == len(right):
            i += 1
        j += 1
    if i < len(left) or j < len(right):
        edits += 1
    return edits == 1


def find_past(event: dict) -> list[tuple[Path, str]]:
    root = VAULT / FOLDER
    if not root.is_dir():
        return []
    emails = [person["email"].casefold() for person in event.get("people", []) if person.get("email")]
    title = event.get("title") or ""
    title_key = title.casefold()
    use_title = len(title) >= 12 and not title.casefold().startswith("meeting ")
    notes: list[dict] = []
    for path in root.rglob("*.md"):
        if path.name == "Index.md" or path.parent.name in {"audio", "Prep"}:
            continue
        resolved = vault_file(path)
        if resolved is None:
            continue
        try:
            if resolved.stat().st_size > 200_000:
                continue
            text = resolved.read_text(encoding="utf-8", errors="replace")[:80_000]
        except OSError:
            continue
        notes.append({
            "path": resolved,
            "mtime": resolved.stat().st_mtime,
            "title": title_of(resolved).casefold(),
            "day": note_day(resolved),
            "insights": resolved.stem.endswith(" — Insights"),
            "people": header_people(text),
            "folded": text.casefold(),
        })

    keys = attendee_keys(event)

    def reason(note: dict) -> str:
        if use_title and titles_related(note["title"], title_key):
            return "title"
        if any(email and email in note["folded"] for email in emails):
            return "email"
        if note["people"] & keys:
            return "people"
        return ""

    def same_meeting(note: dict, seed: dict) -> bool:
        if note["path"] == seed["path"]:
            return True
        if not note["day"] or note["day"] != seed["day"]:
            return False
        return titles_near(note["title"], seed["title"])

    hits = [note for note in notes if reason(note)]
    if any(reason(note) == "title" for note in hits):
        hits = [note for note in hits if reason(note) == "title"]
        hits.sort(key=lambda note: note["mtime"], reverse=True)
    else:
        hits.sort(key=lambda note: (len(note["people"] & keys), note["mtime"]), reverse=True)
    seeds: list[dict] = []
    for note in hits:
        if any(same_meeting(note, seed) for seed in seeds):
            continue
        seeds.append(note)
        if len(seeds) == 3:
            break
    found: list[tuple[Path, str]] = []
    used: set[Path] = set()
    for seed in seeds:
        members = [note for note in notes if same_meeting(note, seed)]
        members.sort(key=lambda note: (not note["insights"], -note["mtime"]))
        why = next(
            (kind for kind in ("title", "email", "people") if any(reason(note) == kind for note in members)),
            "title",
        )
        for note in members:
            if note["path"] in used:
                continue
            used.add(note["path"])
            found.append((note["path"], why))
    return found


def people_line(event: dict) -> str:
    people = event.get("people") or []
    if not people:
        return "Nobody else is listed."
    parts = []
    for person in people:
        name = person.get("name") or "Someone"
        status = person.get("status") or ""
        parts.append(f"{name} ({status})" if status else name)
    return ", ".join(parts)


def context_for(event: dict, past: list[tuple[Path, str]]) -> str:
    summary = event.get("summary") or ""
    prose = invite_prose(event)
    invite = prose or "The invite has no description."
    if prose and len(prose) >= 250:
        invite += " The invite text may be cut off."
    lines = [
        f"Title: {event.get('title', '')}",
        f"When: {event.get('when', '')}",
        f"People: {people_line(event)}",
        f"Summary: {summary or 'None.'}",
        "",
        "Invite:",
        invite,
        "",
        "Past notes:",
    ]
    if not past:
        lines.append("None.")
    for path, why in past:
        try:
            body = excerpt(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        lines.append(f"### {path.stem} ({why})")
        lines.append("Link: " + wiki_link(path))
        lines.append(body or "No notes.")
        lines.append("")
    text = "\n".join(lines).strip()
    encoded = text.encode()
    if len(encoded) <= 24_000:
        return text
    return encoded[:24_000].decode(errors="ignore")


def my_notes_from(path: Path) -> str:
    if not path.is_file():
        return "## My notes\n\n"
    text = path.read_text(encoding="utf-8")
    index = text.find("## My notes")
    if index == -1:
        return "## My notes\n\n"
    return text[index:].rstrip() + "\n"


def obsidian_link(rel_without_suffix: str) -> str:
    query = urllib.parse.urlencode(
        {"vault": VAULT.name, "file": rel_without_suffix},
        quote_via=urllib.parse.quote,
    )
    return "obsidian://open?" + query


def ask(prompt: str, text: str) -> str:
    override = os.environ.get("GIGAMEETING_ASK", "")
    command = [override, prompt] if override else ["omarchy-meeting-recorder", "ask", prompt]
    try:
        result = subprocess.run(
            command,
            input=text,
            capture_output=True,
            text=True,
            timeout=ASK_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def factual_brief(event: dict, past: list[tuple[Path, str]]) -> str:
    what = invite_prose(event) or "The invite has no description."
    if not past:
        last = "This looks like the first one."
        still = "None yet."
        raising = "None yet."
    else:
        notes: list[dict] = []
        for path, _why in past:
            try:
                text = without_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            transcript_at = text.find("## Transcript")
            prose = text if transcript_at == -1 else text[:transcript_at]
            notes.append({
                "path": path,
                "day": note_day(path),
                "title": title_of(path).casefold(),
                "link": wiki_link(path),
                "point": one_sentence(plain_body(prose, "## Summary") or plain_body(prose, "## Insights")),
                "question": one_sentence(plain_body(prose, "## Open questions")),
                "action": one_sentence(plain_body(prose, "## Actions")),
            })
        blocks: list[str] = []
        opens: list[str] = []
        raised: list[str] = []
        index = 0
        while index < len(notes):
            current = notes[index]
            links = [current["link"]]
            point = current["point"]
            question = current["question"]
            action = current["action"]
            nxt = index + 1
            while nxt < len(notes) and notes[nxt]["day"] and notes[nxt]["day"] == current["day"] and titles_near(notes[nxt]["title"], current["title"]):
                links.append(notes[nxt]["link"])
                point = point or notes[nxt]["point"]
                question = question or notes[nxt]["question"]
                action = action or notes[nxt]["action"]
                nxt += 1
            cited = " ".join(links)
            blocks.append(f"{point} {cited}".strip() if point else cited)
            if question:
                opens.append(f"{question} {links[0]}")
            if action:
                raised.append(f"{action} {links[0]}")
            index = nxt
        last = "\n\n".join(blocks) or "This looks like the first one."
        still = "\n\n".join(opens) if opens else "None yet."
        raising = raised[0] if raised else "None yet."
    return (
        f"## What this is\n\n{what}\n\n"
        f"## Last time\n\n{last}\n\n"
        f"## Still open\n\n{still}\n\n"
        f"## Worth raising\n\n{raising}\n"
    )


def brief_body(event: dict, past: list[tuple[Path, str]]) -> str:
    answer = ask(BRIEF_PROMPT, context_for(event, past))
    if "## What this is" in answer and "## Worth raising" in answer:
        return answer.rstrip() + "\n"
    return factual_brief(event, past)


def unescape_yaml(value: str) -> str:
    out = []
    index = 0
    while index < len(value):
        if value[index] == "\\" and index + 1 < len(value):
            out.append(value[index + 1])
            index += 2
            continue
        out.append(value[index])
        index += 1
    return "".join(out)


def prep_index() -> dict[tuple[str, str], str]:
    directory = VAULT / FOLDER / "Prep"
    if not directory.is_dir():
        return {}
    index: dict[tuple[str, str], str] = {}
    try:
        base = VAULT.resolve(strict=True)
    except OSError:
        return {}
    for path in directory.glob("*.md"):
        resolved = vault_file(path)
        if resolved is None:
            continue
        try:
            head = resolved.read_text(encoding="utf-8", errors="replace")[:1200]
        except OSError:
            continue
        found_day = DATE_LINE_RE.search(head)
        found_event = EVENT_RE.search(head)
        if not found_day or not found_event:
            continue
        event_id = unescape_yaml(found_event.group(1))
        if not event_id or len(event_id) > 80 or any(char in event_id for char in "\n\r\x00"):
            continue
        key = (event_id, found_day.group(1))
        if key in index:
            continue
        rel = resolved.relative_to(base).with_suffix("")
        index[key] = obsidian_link(str(rel))
    return index


def matching_preps(event_id: str, day: str) -> list[Path]:
    directory = VAULT / FOLDER / "Prep"
    if not directory.is_dir():
        return []
    needle = f"event: {yaml_quote(event_id)}"
    found: list[Path] = []
    for path in sorted(directory.glob("*.md")):
        resolved = vault_file(path)
        if resolved is None:
            continue
        try:
            head = resolved.read_text(encoding="utf-8", errors="replace")[:1200]
        except OSError:
            continue
        if needle in head and f"date: {day}" in head:
            found.append(resolved)
    return found


def existing_prep(event_id: str, day: str) -> Path | None:
    found = matching_preps(event_id, day)
    return found[0] if found else None


def cmd_prep(key: str) -> None:
    parsed = split_key(key)
    event = event_by_id(key)
    if parsed is None or not event or not event.get("title"):
        fail("that meeting is no longer on the list")
    hey_id, day = parsed
    if event.get("date") != day:
        fail("that meeting is no longer on the list")
    directory = VAULT / FOLDER / "Prep"
    directory.mkdir(parents=True, exist_ok=True)
    old = matching_preps(hey_id, day)
    notes = my_notes_from(old[0]) if old else "## My notes\n\n"
    removed = {path.resolve() for path in old}
    deleted = False
    for path in old:
        try:
            path.unlink()
        except OSError:
            if deleted:
                # The card drops Brief only after it sees this line.
                print("replaced", flush=True)
            fail("could not replace the old brief")
        deleted = True
    if deleted:
        print("replaced", flush=True)
    path = directory / f"{day} {safe_title(event['title'])}.md"
    if path.exists() and path.resolve() not in removed:
        fail("could not replace the old brief")
    past = find_past(event)
    people = event.get("people") or []
    lines = [
        "---",
        f"date: {day}",
        "type: prep",
        "source: hey",
        f"event: {yaml_quote(hey_id)}",
        f"title: {yaml_quote(event['title'])}",
    ]
    emails = [person["email"] for person in people if person.get("email")]
    names = [person["name"] for person in people if person.get("name")]
    if names:
        lines.append("people:")
        lines.extend(f"  - {yaml_quote(name)}" for name in names)
    if emails:
        lines.append("emails:")
        lines.extend(f"  - {yaml_quote(email)}" for email in emails)
    lines.append("---")
    lines.append("")
    lines.append(f"# {event['title']}")
    lines.append("")
    lines.append(brief_body(event, past).rstrip())
    lines.append("")
    lines.append(notes.rstrip())
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    rel = path.relative_to(VAULT).with_suffix("")
    print("ready " + obsidian_link(str(rel)))


def cmd_open_note(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "obsidian" or parsed.netloc != "open":
        fail("not a vault note")
    query = urllib.parse.parse_qs(parsed.query)
    vault = (query.get("vault") or [""])[0]
    rel = (query.get("file") or [""])[0]
    if vault != VAULT.name or not rel or rel.startswith("/") or ".." in Path(rel).parts:
        fail("not a vault note")
    path = vault_file(VAULT / (rel if rel.endswith(".md") else rel + ".md"))
    if path is None:
        fail("not a vault note")
    link = obsidian_link(str(path.relative_to(VAULT.resolve()).with_suffix("")))
    if not launch(link):
        fail("could not open the note")
    print("opened")


def one_line(value: object, limit: int) -> str:
    text = "".join(ch for ch in plain(value, limit * 2) if ch.isprintable())
    return " ".join(text.split())[:limit].strip()


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    return data if isinstance(data, dict) else {}


def meeting_folder(meeting_id: str) -> Path | None:
    if not isinstance(meeting_id, str) or not meeting_id or len(meeting_id) > 180:
        return None
    if any(char in meeting_id for char in "\n\r\x00/\\") or meeting_id in {".", ".."}:
        return None
    if not MEETINGS.is_dir():
        return None
    try:
        base = MEETINGS.resolve(strict=True)
        resolved = (MEETINGS / meeting_id).resolve(strict=True)
    except OSError:
        return None
    if resolved.parent != base or not resolved.is_dir() or resolved.name != meeting_id:
        return None
    return resolved


def contained_file(folder: Path, name: str) -> Path | None:
    """A direct file in the meeting folder, or a symlink to one under Meetings."""
    if not name or name in {".", ".."} or any(char in name for char in "/\\\n\r\x00"):
        return None
    entry = folder / name
    if entry.parent != folder:
        return None
    try:
        resolved = entry.resolve(strict=True)
        root = MEETINGS.resolve(strict=True)
    except OSError:
        return None
    if not resolved.is_file() or root not in resolved.parents:
        return None
    return resolved


def recording_file(folder: Path) -> Path | None:
    preferred = contained_file(folder, "audio.ogg")
    if preferred is not None:
        return preferred
    try:
        names = sorted(
            path.name
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES
        )
    except OSError:
        return None
    for name in names:
        found = contained_file(folder, name)
        if found is not None:
            return found
    return None


def note_link(rel: object) -> str:
    if not isinstance(rel, str) or not rel or len(rel) > 300:
        return ""
    if rel.startswith("/") or any(char in rel for char in "\n\r\x00") or ".." in Path(rel).parts:
        return ""
    path = vault_file(VAULT / (rel if rel.endswith(".md") else rel + ".md"))
    if path is None:
        return ""
    return obsidian_link(str(path.relative_to(VAULT.resolve()).with_suffix("")))


def manifest_of(folder: Path) -> dict:
    found = sorted(folder.glob("*.meeting-recorder"))
    return read_json(found[0]) if found else {}


def started_stamp(folder: Path, manifest: dict, sidecar: dict) -> float:
    for source in (manifest, sidecar):
        value = source.get("started_at")
        if isinstance(value, str) and value.isdigit():
            value = float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 1_000_000_000:
            return float(value)
    name = folder.name
    if len(name) >= 12 and name[:12].isdigit():
        try:
            return datetime.strptime(name[:12], "%Y%m%d%H%M").timestamp()
        except ValueError:
            pass
    try:
        return folder.stat().st_mtime
    except OSError:
        return 0.0


def when_label(stamp: float) -> str:
    moment = datetime.fromtimestamp(stamp).astimezone()
    today = datetime.now().astimezone().date()
    day = moment.date()
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    if moment.year == today.year:
        return moment.strftime("%b %-d")
    return moment.strftime("%b %-d, %Y")


def meeting_title(folder: Path, manifest: dict, sidecar: dict) -> str:
    for source in (sidecar, manifest):
        title = one_line(source.get("title"), 120)
        if title:
            return title
    name = folder.name
    if len(name) > 13 and name[:12].isdigit() and name[12] == " ":
        name = name[13:]
    return one_line(name, 120) or "Meeting"


def describe_meeting(folder: Path) -> dict | None:
    sidecar = read_json(folder / ".obsidian-filed.json")
    manifest = manifest_of(folder)
    recording = recording_file(folder) is not None
    transcript = bool(note_link(sidecar.get("transcript_rel"))) or contained_file(folder, "transcript.md") is not None
    insights = bool(note_link(sidecar.get("insights_rel")))
    if not recording and not transcript and not insights:
        return None
    stamp = started_stamp(folder, manifest, sidecar)
    moment = datetime.fromtimestamp(stamp).astimezone()
    return {
        "id": folder.name,
        "title": meeting_title(folder, manifest, sidecar),
        "day": when_label(stamp),
        "time": moment.strftime("%H:%M"),
        "recording": recording,
        "transcript": transcript,
        "insights": insights,
        "stamp": stamp,
    }


def cmd_recent() -> None:
    if not MEETINGS.is_dir():
        print(json.dumps({"meetings": []}, ensure_ascii=False))
        return
    try:
        base = MEETINGS.resolve(strict=True)
        entries = [path for path in MEETINGS.iterdir() if path.is_dir()]
    except OSError:
        print(json.dumps({"meetings": []}, ensure_ascii=False))
        return
    seen: set[Path] = set()
    rows: list[dict] = []
    for path in entries:
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            continue
        if resolved.parent != base or resolved in seen or resolved.name != path.name:
            continue
        if len(path.name) > 180 or any(char in path.name for char in "\n\r\x00/\\"):
            continue
        seen.add(resolved)
        row = describe_meeting(resolved)
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda row: row["stamp"], reverse=True)
    card = [{key: row[key] for key in ("id", "title", "day", "time", "recording", "transcript", "insights")} for row in rows[:MAX_RECENT]]
    print(json.dumps({"meetings": card}, ensure_ascii=False))


def launch(target: str) -> bool:
    """Start the handler and return. Do not wait for the app itself.

    xdg-open waits until Obsidian exits, so the first note pinned every later
    link. gio hands the link off and returns. A handler still running after a
    few seconds counts as opened and is left running in its own session.
    """
    if not target:
        return False
    gio = shutil.which("gio")
    argv = [gio, "open", target] if gio else ["xdg-open", target]
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return False
    try:
        code = proc.wait(timeout=OPEN_WAIT)
    except subprocess.TimeoutExpired:
        return True
    return code == 0


def cmd_audio(meeting_id: str) -> None:
    folder = meeting_folder(meeting_id)
    if folder is None:
        fail("not a recording")
    path = recording_file(folder)
    if path is None:
        fail("no recording")
    print(path)


def cmd_open_recent(meeting_id: str, kind: str) -> None:
    folder = meeting_folder(meeting_id)
    if folder is None or kind not in {"recording", "transcript", "insights"}:
        fail("not a recording")
    sidecar = read_json(folder / ".obsidian-filed.json")
    if kind == "recording":
        path = recording_file(folder)
        if path is None:
            fail("no recording")
        if not launch(str(path)):
            fail("could not open")
    elif kind == "transcript":
        link = note_link(sidecar.get("transcript_rel"))
        path = contained_file(folder, "transcript.md")
        if link:
            if not launch(link):
                fail("could not open")
        elif path is not None:
            if not launch(str(path)):
                fail("could not open")
        else:
            fail("no transcript")
    else:
        link = note_link(sidecar.get("insights_rel"))
        if not link:
            fail("no insights")
        if not launch(link):
            fail("could not open")
    print("opened")


def main(argv: list[str]) -> None:
    command = argv[1] if len(argv) > 1 else ""
    if command == "day":
        cmd_day()
    elif command == "agenda":
        cmd_agenda()
    elif command == "open-event" and len(argv) == 3:
        cmd_open_event(argv[2])
    elif command == "prep" and len(argv) == 3:
        cmd_prep(argv[2])
    elif command == "open-note" and len(argv) == 3:
        cmd_open_note(argv[2])
    elif command == "recent":
        cmd_recent()
    elif command == "open-recent" and len(argv) == 4:
        cmd_open_recent(argv[2], argv[3])
    elif command == "audio" and len(argv) == 3:
        cmd_audio(argv[2])
    else:
        print(
            "Usage: calendar.py day|agenda|open-event <id>|prep <id>|open-note <url>|recent|open-recent <id> <kind>|audio <id>",
            file=sys.stderr,
        )
        raise SystemExit(2)


def _unshadow_stdlib() -> None:
    """Drop this directory from sys.path while the file runs as a script.

    The file is named calendar.py. Python puts its folder first on the path,
    and datetime.strptime then imports this file instead of the stdlib.
    """
    here = Path(__file__).resolve().parent
    kept = []
    for entry in sys.path:
        try:
            same = bool(entry) and Path(entry).resolve() == here
        except OSError:
            same = False
        if not same:
            kept.append(entry)
    sys.path[:] = kept


if __name__ == "__main__":
    _unshadow_stdlib()
    main(sys.argv)
