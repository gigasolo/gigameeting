#!/usr/bin/env python3
"""Today's meetings, and recent recordings, for the GigaMeeting card.

`day` reads HEY's day view. The card gets titles and clock times. The join
link, invite text, and people stay in a private cache for Prep. If HEY
cannot be reached, `day` falls back to one OmaCal offer and no list.

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

VAULT = Path(os.path.expanduser(os.environ.get("OBSIDIAN_VAULT", "~/Documents/Obsidian")))
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
WINDOW_MS = 15 * 60 * 1000
MAX_EVENTS = 8
MAX_RECENT = 6
AUDIO_SUFFIXES = {".ogg", ".opus", ".mp3", ".wav", ".m4a", ".flac"}
OPEN_WAIT = 3
ASK_TIMEOUT = 120
ILLEGAL = re.compile(r'[\\/:*?"<>|]')
TAG = re.compile(r"<[^>]+>")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
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


def local_today() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


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


def normalize_hey(rows: list, now_ms: float) -> list[dict]:
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
                "url": join_url(row.get("join_link")),
                "summary": plain(row.get("summary"), 500),
                "description": plain(row.get("description"), 4000),
                "people": people_of(row),
            }
        )
    events.sort(key=lambda item: item["start"])
    return events[:MAX_EVENTS]


def hey_rows() -> list | None:
    try:
        out = subprocess.run(
            ["hey", "event", "day", "--quiet", "--json"],
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


def omacal_offer(now_ms: float | None = None) -> dict | None:
    try:
        out = subprocess.run(
            ["omacal", "agenda", "--days", "1", "--json"],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    try:
        payload = json.loads(out.stdout)
    except json.JSONDecodeError:
        return None
    rows = payload.get("data") if isinstance(payload, dict) and payload.get("ok") else None
    if not isinstance(rows, list):
        return None
    now = time.time() * 1000 if now_ms is None else now_ms
    current, upcoming = [], []
    for row in rows:
        if not isinstance(row, dict) or row.get("allDay"):
            continue
        title = plain(row.get("title"), 200)
        start, end = row.get("startMs"), row.get("endMs")
        if not title or not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            continue
        if end <= now:
            continue
        url = join_url(row.get("conference"))
        item = (start, title, url, clock_range(row.get("start"), row.get("end")))
        if start <= now:
            current.append(item)
        elif start - now <= WINDOW_MS:
            upcoming.append(item)
    if current:
        current.sort(key=lambda item: (bool(item[2]), item[0]))
        chosen = current[-1]
    elif upcoming:
        upcoming.sort(key=lambda item: item[0])
        chosen = upcoming[0]
    else:
        return None
    _start, title, url, when = chosen
    return {"title": title, "when": when, "url": url}


def write_cache(events: list[dict]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps({"date": local_today(), "events": events}, ensure_ascii=False)
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
    if not isinstance(payload, dict) or payload.get("date") != local_today():
        return []
    events = payload.get("events")
    return events if isinstance(events, list) else []


def card_event(event: dict) -> dict:
    return {
        "id": event["id"],
        "title": event["title"],
        "when": event["when"],
        "start": event["start"],
        "end": event["end"],
        "hasUrl": bool(event.get("url")),
    }


def cmd_day() -> None:
    rows = hey_rows()
    if rows is not None:
        events = normalize_hey(rows, time.time() * 1000)
        try:
            write_cache(events)
        except OSError:
            events = [{**event, "url": ""} for event in events]
        print(json.dumps({"source": "hey", "events": [card_event(event) for event in events]}, ensure_ascii=False))
        return
    offer = omacal_offer()
    print(json.dumps({"source": "omacal", "events": [], "offer": offer}, ensure_ascii=False))


def cmd_agenda() -> None:
    offer = omacal_offer()
    if offer:
        print(json.dumps(offer, ensure_ascii=False))


def event_by_id(event_id: str) -> dict | None:
    if not event_id or any(char in event_id for char in "\n\r\x00"):
        return None
    for event in read_cache():
        if isinstance(event, dict) and str(event.get("id")) == event_id:
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


def excerpt(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4:]
    cut = text.find("## Transcript")
    if cut != -1:
        text = text[:cut]
    chunks = [section(text, heading) for heading in HEADINGS]
    blob = "\n\n".join(chunk for chunk in chunks if chunk).strip()
    if not blob:
        blob = text.strip()[:600]
    return blob[:1500]


def title_of(path: Path) -> str:
    stem = path.stem
    if stem.endswith(" — Insights"):
        stem = stem[: -len(" — Insights")]
    if len(stem) > 11 and stem[10] == " " and stem[4] == "-" and stem[:4].isdigit():
        stem = stem[11:]
    return stem.strip()


def find_past(event: dict) -> list[tuple[Path, str]]:
    root = VAULT / FOLDER
    if not root.is_dir():
        return []
    emails = [person["email"].casefold() for person in event.get("people", []) if person.get("email")]
    title = event.get("title") or ""
    title_key = title.casefold()
    use_title = len(title) >= 12 and not title.casefold().startswith("meeting ")
    found: list[tuple[float, Path, str]] = []
    for path in root.rglob("*.md"):
        if path.name == "Index.md" or path.parent.name == "audio":
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
        folded = text.casefold()
        why = ""
        if any(email and email in folded for email in emails):
            why = "email"
        elif use_title and title_of(resolved).casefold() == title_key:
            why = "title"
        if not why:
            continue
        found.append((resolved.stat().st_mtime, resolved, why))
    found.sort(key=lambda item: item[0], reverse=True)
    email_hits = [item for item in found if item[2] == "email"][:3]
    if email_hits:
        return [(path, why) for _mtime, path, why in email_hits]
    return [(path, why) for _mtime, path, why in found[:3]]


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
    description = event.get("description") or ""
    summary = event.get("summary") or ""
    invite = description or "The invite has no description."
    if description and len(description) >= 250:
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
    description = event.get("description") or ""
    summary = event.get("summary") or ""
    what = description or "The invite has no description."
    if summary and summary not in what:
        what = summary + "\n\n" + what
    if not past:
        last = "This looks like the first one."
        still = "None yet."
    else:
        blocks = []
        for path, _why in past:
            try:
                body = excerpt(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if body:
                blocks.append(f"**{path.stem}**\n\n{body}")
        last = "\n\n".join(blocks) or "This looks like the first one."
        still = "None yet."
    raising = "None yet." if not past else "See what was left open last time."
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


def existing_prep(event_id: str, day: str) -> Path | None:
    directory = VAULT / FOLDER / "Prep"
    if not directory.is_dir():
        return None
    needle = f"event: {yaml_quote(event_id)}"
    for path in directory.glob("*.md"):
        resolved = vault_file(path)
        if resolved is None:
            continue
        head = resolved.read_text(encoding="utf-8", errors="replace")[:1200]
        if needle in head and f"date: {day}" in head:
            return resolved
    return None


def cmd_prep(event_id: str) -> None:
    event = event_by_id(event_id)
    if not event or not event.get("title"):
        fail("that meeting is no longer on today's list")
    past = find_past(event)
    day = local_today()
    directory = VAULT / FOLDER / "Prep"
    directory.mkdir(parents=True, exist_ok=True)
    path = existing_prep(event_id, day) or (directory / f"{day} {safe_title(event['title'])}.md")
    notes = my_notes_from(path)
    people = event.get("people") or []
    lines = [
        "---",
        f"date: {day}",
        "type: prep",
        "source: hey",
        f"event: {yaml_quote(event_id)}",
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
