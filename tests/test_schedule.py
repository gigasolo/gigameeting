#!/usr/bin/env python3
"""Schedule and prep-link tests for calendar.py.

Load the helper under another module name. Running this file as a script
would put its directory first on the path, and a module named calendar.py
then shadows the stdlib calendar module that datetime imports.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

CALENDAR = Path("/home/lonbaker/code/gigameeting/calendar.py")


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class ScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.vault = root / "Obsidian"
        (self.vault / "Meetings" / "Prep").mkdir(parents=True)
        self.state = root / "day.json"
        os.environ["OBSIDIAN_VAULT"] = str(self.vault)
        os.environ["OBSIDIAN_FOLDER"] = "Meetings"
        os.environ["GIGAMEETING_STATE"] = str(self.state)
        os.environ["GIGAMEETING_ASK"] = "/bin/true"
        os.environ["MEETINGS_ROOT"] = str(root / "recordings")
        sys.modules.pop("gigameeting_calendar", None)
        spec = importlib.util.spec_from_file_location("gigameeting_calendar", CALENDAR)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        self.mod = module

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_normalize_hey_keeps_one_upcoming_timed_event(self) -> None:
        base = datetime(2026, 10, 4, 20, 0, tzinfo=timezone.utc)
        now_ms = base.timestamp() * 1000
        rows = [
            {
                "id": 5,
                "title": "Later today",
                "starts_at": stamp(base + timedelta(hours=1)),
                "ends_at": stamp(base + timedelta(hours=2)),
            },
            {
                "id": 6,
                "title": "Done",
                "starts_at": stamp(base - timedelta(hours=2)),
                "ends_at": stamp(base - timedelta(hours=1)),
            },
            {
                "id": 7,
                "title": "Home",
                "all_day": True,
                "starts_at": stamp(base),
                "ends_at": stamp(base + timedelta(hours=1)),
            },
        ]
        kept = self.mod.normalize_hey(rows, now_ms, "2026-10-04")
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["id"], "5")
        self.assertEqual(kept[0]["date"], "2026-10-04")
        self.assertEqual(kept[0]["title"], "Later today")

    def test_same_hey_id_on_two_days_stays_two_rows(self) -> None:
        base = datetime(2026, 10, 4, 20, 0, tzinfo=timezone.utc)
        now_ms = base.timestamp() * 1000
        today = self.mod.normalize_hey(
            [{
                "id": 5,
                "title": "Today standup",
                "starts_at": stamp(base + timedelta(hours=1)),
                "ends_at": stamp(base + timedelta(hours=2)),
            }],
            now_ms,
            "2026-10-04",
        )
        tomorrow = self.mod.normalize_hey(
            [{
                "id": 5,
                "title": "Tomorrow standup",
                "starts_at": stamp(base + timedelta(days=1)),
                "ends_at": stamp(base + timedelta(days=1, hours=1)),
            }],
            now_ms,
            "2026-10-05",
        )
        merged = today + tomorrow
        self.assertEqual([row["date"] for row in merged], ["2026-10-04", "2026-10-05"])
        self.assertEqual([row["title"] for row in merged], ["Today standup", "Tomorrow standup"])
        self.assertEqual({row["id"] for row in merged}, {"5"})

    def write_prep(self, day: str) -> None:
        path = self.vault / "Meetings" / "Prep" / f"{day} Alignment.md"
        path.write_text(
            "\n".join([
                "---",
                f"date: {day}",
                "type: prep",
                "source: hey",
                'event: "176681968"',
                'title: "Alignment"',
                "---",
                "",
                "# Alignment",
                "",
            ]),
            encoding="utf-8",
        )

    def test_brief_matches_event_and_date(self) -> None:
        self.write_prep("2026-10-04")
        event = {
            "id": "176681968",
            "title": "Alignment",
            "when": "07:30–08:10",
            "start": 1,
            "end": 2,
            "date": "2026-10-05",
            "url": "",
        }
        missed = self.mod.card_event(event, self.mod.prep_index())
        self.assertEqual(missed["id"], "176681968@2026-10-05")
        self.assertEqual(missed["brief"], "")
        self.write_prep("2026-10-05")
        found = self.mod.card_event(event, self.mod.prep_index())
        self.assertTrue(found["brief"].startswith("obsidian://open?"))
        self.assertNotIn("2026-10-04", found["brief"])

    def test_open_obsidian_vault_is_preferred(self) -> None:
        found = self.mod.vault_from_obsidian_config({
            "vaults": {
                "one": {"path": "/tmp/other", "open": False},
                "two": {"path": "/home/lonbaker/Obsidian", "open": True},
            }
        })
        self.assertEqual(found, Path("/home/lonbaker/Obsidian"))
        self.assertIsNone(self.mod.vault_from_obsidian_config({"vaults": {}}))
        self.assertIsNone(self.mod.vault_from_obsidian_config({
            "vaults": {
                "a": {"path": "/tmp/a", "open": True},
                "b": {"path": "/tmp/b", "open": True},
            }
        }))

    def test_split_key_rejects_a_bare_id_a_newline_and_a_bad_date(self) -> None:
        self.assertIsNone(self.mod.split_key("176681968"))
        self.assertIsNone(self.mod.split_key("176681968\n@2026-10-05"))
        self.assertIsNone(self.mod.split_key("176681968@2026-13-40"))
        self.assertEqual(self.mod.split_key("176681968@2026-10-05"), ("176681968", "2026-10-05"))

    def test_old_cache_without_tomorrow_is_ignored(self) -> None:
        today = self.mod.local_day(0)
        self.state.write_text(json.dumps({"date": today, "events": [{"id": "5"}]}), encoding="utf-8")
        self.assertEqual(self.mod.read_cache(), [])

    def test_prep_uses_the_meeting_date_and_prints_the_link(self) -> None:
        today = self.mod.local_day(0)
        tomorrow = self.mod.local_day(1)
        self.mod.write_cache(today, tomorrow, [{
            "id": "176681968",
            "title": "Alignment",
            "when": "07:30–08:10",
            "start": 1,
            "end": 2,
            "date": tomorrow,
            "url": "",
            "summary": "",
            "description": "Talk about the week.",
            "people": [],
        }])
        self.assertIsNone(self.mod.event_by_id("176681968"))
        from io import StringIO
        import contextlib
        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            self.mod.cmd_prep(f"176681968@{tomorrow}")
        lines = buf.getvalue().splitlines()
        self.assertTrue(lines[-1].startswith("ready obsidian://open?"))
        self.assertNotIn("replaced", lines)
        notes = list((self.vault / "Meetings" / "Prep").glob("*.md"))
        self.assertEqual(len(notes), 1)
        self.assertTrue(notes[0].name.startswith(tomorrow + " "))
        body = notes[0].read_text(encoding="utf-8")
        self.assertIn(f"date: {tomorrow}", body)
        self.assertIn('event: "176681968"', body)
        self.assertNotIn(f"event: \"176681968@{tomorrow}\"", body)

    def test_prep_again_removes_the_old_note(self) -> None:
        today = self.mod.local_day(0)
        tomorrow = self.mod.local_day(1)
        self.mod.write_cache(today, tomorrow, [{
            "id": "176681968",
            "title": "Alignment",
            "when": "07:30–08:10",
            "start": 1,
            "end": 2,
            "date": tomorrow,
            "url": "",
            "summary": "",
            "description": "Talk about the week.",
            "people": [],
        }])
        folder = self.vault / "Meetings" / "Prep"
        stale = folder / f"{tomorrow} Old title.md"
        duplicate = folder / f"{tomorrow} Also old.md"
        same = folder / f"{tomorrow} Alignment.md"
        note = f'---\ndate: {tomorrow}\ntype: prep\nsource: hey\nevent: "176681968"\n---\n# Old\n\n## My notes\n\nKeep this\n'
        stale.write_text(note, encoding="utf-8")
        duplicate.write_text(note, encoding="utf-8")
        same.write_text(note, encoding="utf-8")
        from io import StringIO
        import contextlib
        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            self.mod.cmd_prep(f"176681968@{tomorrow}")
        lines = buf.getvalue().splitlines()
        self.assertIn("replaced", lines)
        self.assertTrue(lines[-1].startswith("ready obsidian://open?"))
        self.assertFalse(stale.exists())
        self.assertFalse(duplicate.exists())
        notes = list(folder.glob("*.md"))
        self.assertEqual(notes, [same])
        body = same.read_text(encoding="utf-8")
        self.assertIn("Keep this", body)
        self.assertIn("## My notes", body)

    def test_prep_keeps_the_note_when_the_meeting_is_gone(self) -> None:
        tomorrow = self.mod.local_day(1)
        folder = self.vault / "Meetings" / "Prep"
        stale = folder / f"{tomorrow} Old title.md"
        note = f'---\ndate: {tomorrow}\ntype: prep\nsource: hey\nevent: "176681968"\n---\n# Old\n\n## My notes\n\nKeep this\n'
        stale.write_text(note, encoding="utf-8")
        from io import StringIO
        import contextlib
        buf = StringIO()
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stdout(buf):
                self.mod.cmd_prep(f"176681968@{tomorrow}")
        self.assertTrue(stale.exists())
        self.assertIn("failed:", buf.getvalue())
        self.assertNotIn("replaced", buf.getvalue().splitlines())

    def test_past_notes_pair_a_mistyped_insight_with_its_transcript(self) -> None:
        folder = self.vault / "Meetings"
        day = "2026-10-01"
        transcript = folder / f"{day} Marketing Reset Meeting.md"
        insights = folder / f"{day} Mrketing Reset Meeting — Insights.md"
        other = folder / f"{day} Bandwidth Renewal Notice Required.md"
        filler = "word " * 400
        transcript.write_text(
            "---\ndate: 2026-10-01\n---\n# Marketing Reset Meeting\n\n"
            "## Transcript\n\nSTARTMARK " + filler + " ENDMARK\n",
            encoding="utf-8",
        )
        insights.write_text(
            "---\ndate: 2026-10-01\n---\n# Mrketing\n\n"
            "## Open questions\n\nIs the trial live?\n\n## Insights\n\nPaid is the fast path.\n",
            encoding="utf-8",
        )
        other.write_text("## Summary\n\nUnrelated renewal.\n", encoding="utf-8")
        event = {
            "title": "Marketing Reset Meeting",
            "people": [{"email": "ada@example.com"}],
        }
        # The transcript is the only file with the address. The insight note still comes along.
        transcript.write_text(
            transcript.read_text(encoding="utf-8") + "\nada@example.com\n",
            encoding="utf-8",
        )
        found = self.mod.find_past(event)
        names = [path.name for path, _why in found]
        self.assertIn(transcript.name, names)
        self.assertIn(insights.name, names)
        self.assertNotIn(other.name, names)
        text = self.mod.context_for(event, found)
        self.assertLessEqual(len(text.encode()), 24_000)
        self.assertIn("Is the trial live?", text)
        self.assertIn("[[Meetings/2026-10-01 Marketing Reset Meeting]]", text)
        self.assertNotIn("STARTMARK", text)
        self.assertNotIn("ENDMARK", text)

    def test_a_different_meeting_on_the_same_day_stays_out(self) -> None:
        folder = self.vault / "Meetings"
        day = "2026-10-01"
        near = folder / f"{day} Marketng Reset Meeting.md"
        far = folder / f"{day} Bandwidth Renewal Notice Required.md"
        near.write_text("## Summary\n\nAlmost the same name.\n", encoding="utf-8")
        far.write_text("## Summary\n\nA renewal.\n", encoding="utf-8")
        found = self.mod.find_past({"title": "Marketing Reset Meeting", "people": []})
        names = {path.name for path, _why in found}
        self.assertIn(near.name, names)
        self.assertNotIn(far.name, names)

    def test_context_stays_within_the_ask_cap(self) -> None:
        folder = self.vault / "Meetings"
        path = folder / "2026-09-30 All-Hands Meeting Q4 2026.md"
        path.write_text("## Transcript\n\n" + ("sentence " * 20_000), encoding="utf-8")
        event = {"title": "All-Hands Meeting Q4 2026", "description": "x" * 500, "people": []}
        text = self.mod.context_for(event, self.mod.find_past(event))
        self.assertLessEqual(len(text.encode()), 24_000)
        self.assertIn("Transcript only.", text)
        self.assertNotIn("sentence sentence sentence", text)

    def test_brief_cites_the_notes_instead_of_pasting_them(self) -> None:
        folder = self.vault / "Meetings"
        day = "2026-10-01"
        transcript = folder / f"{day} Marketing Reset Meeting.md"
        insights = folder / f"{day} Mrketing Reset Meeting — Insights.md"
        filler = "word " * 400
        transcript.write_text(
            "---\ndate: 2026-10-01\n---\n# Marketing Reset Meeting\n\n"
            "## Transcript\n\nSTARTMARK " + filler + " ENDMARK\n",
            encoding="utf-8",
        )
        insights.write_text(
            "---\ndate: 2026-10-01\n---\n# Mrketing\n\n"
            "## Open questions\n\nIs the trial live?\n\n## Insights\n\nPaid is the fast path.\n",
            encoding="utf-8",
        )
        event = {"title": "Marketing Reset Meeting", "description": "Weekly reset.", "people": []}
        found = self.mod.find_past(event)
        context = self.mod.context_for(event, found)
        insight_link = "[[Meetings/2026-10-01 Mrketing Reset Meeting — Insights]]"
        transcript_link = "[[Meetings/2026-10-01 Marketing Reset Meeting]]"
        self.assertIn("Link: " + insight_link, context)
        self.assertIn("Link: " + transcript_link, context)
        brief = self.mod.factual_brief(event, found)
        self.assertIn("Paid is the fast path.", brief)
        self.assertIn("Is the trial live?", brief)
        self.assertIn("Weekly reset", brief)
        self.assertIn(insight_link, brief)
        self.assertIn(transcript_link, brief)
        self.assertNotIn("STARTMARK", brief)
        self.assertNotIn("ENDMARK", brief)
        self.assertNotIn("word word word", brief)
        last = brief.split("## Still open", 1)[0]
        self.assertLess(len(last), 500)

    def test_earlier_prep_notes_are_not_sources(self) -> None:
        folder = self.vault / "Meetings"
        day = "2026-10-01"
        prep = folder / "Prep" / f"{day} Marketing Reset Meeting.md"
        prep.write_text(
            "---\ndate: 2026-10-01\nevent: \"1\"\n---\n"
            "## Last time\n\nPREPONLYMARKER pasted from an earlier brief.\n"
            "ada@example.com\nprep-only@example.com\n",
            encoding="utf-8",
        )
        transcript = folder / f"{day} Marketing Reset Meeting.md"
        transcript.write_text(
            "## Summary\n\nThe real point.\n\nada@example.com\n",
            encoding="utf-8",
        )
        event = {
            "title": "Marketing Reset Meeting",
            "people": [{"email": "ada@example.com"}],
        }
        found = self.mod.find_past(event)
        self.assertEqual([path.name for path, _why in found], [transcript.name])
        text = self.mod.context_for(event, found) + self.mod.factual_brief(event, found)
        self.assertIn("The real point.", text)
        self.assertNotIn("PREPONLYMARKER", text)
        only_prep = {"title": "Bandwidth Renewal Notice Required", "people": [{"email": "prep-only@example.com"}]}
        self.assertEqual(self.mod.find_past(only_prep), [])

    def test_named_people_match_when_the_note_has_no_email(self) -> None:
        folder = self.vault / "Meetings"
        band = folder / "2026-10-02 Bandwidth Renewal Notice Required — Insights.md"
        band.write_text(
            "---\ndate: 2026-10-02\npeople:\n  - \"[[Rachel]]\"\n  - \"[[Justin]]\"\n---\n"
            "# Bandwidth\n\n## Summary\n\nThey locked the renewal.\n\n"
            "## Open questions\n\nDoes the 30-day trial still need a card?\n",
            encoding="utf-8",
        )
        rachel = folder / "2026-10-01 Marketing Reset Meeting — Insights.md"
        rachel.write_text(
            "---\ndate: 2026-10-01\npeople:\n  - \"[[Rachel]]\"\n---\n"
            "## Summary\n\nAcquisition is the priority.\n",
            encoding="utf-8",
        )
        other = folder / "2026-09-29 Lead Gen Recording — Insights.md"
        other.write_text(
            "---\ndate: 2026-09-29\npeople:\n  - \"[[Taylor]]\"\n---\n"
            "## Summary\n\nA different room.\n",
            encoding="utf-8",
        )
        event = {
            "title": "Alignment & Priorities",
            "summary": "Alignment & Priorities",
            "description": (
                "Join with Google Meet: https://meet.google.com/abc "
                "Or dial: (US) +1 570-630-1482 PIN: 143791731# "
                "Learn more about Meet at: https://support.google.com/a/users/answer/9282720"
            ),
            "people": [
                {"name": "Rachel Anderson", "email": "rachel.anderson@virtualpbx.com"},
                {"name": "justin.goodpaster@virtualpbx.com", "email": "justin.goodpaster@virtualpbx.com"},
            ],
        }
        found = self.mod.find_past(event)
        names = [path.name for path, _why in found]
        self.assertEqual(names[0], band.name)
        self.assertIn(rachel.name, names)
        self.assertNotIn(other.name, names)
        brief = self.mod.factual_brief(event, found)
        self.assertIn("They locked the renewal.", brief)
        self.assertIn("[[Meetings/2026-10-02 Bandwidth Renewal Notice Required — Insights]]", brief)
        self.assertIn("The invite has no description.", brief)
        self.assertNotIn("meet.google.com", brief)
        self.assertNotIn("This looks like the first one.", brief)

    def test_a_renamed_series_beats_a_shared_teammate(self) -> None:
        folder = self.vault / "Meetings"
        prior = folder / "2026-09-30 X Social Listening Discussion — Insights.md"
        prior.write_text(
            "---\ndate: 2026-09-30\npeople:\n  - \"[[Joel]]\"\n---\n"
            "## Summary\n\nThe digest was empty.\n",
            encoding="utf-8",
        )
        other = folder / "2026-10-02 Bandwidth Renewal Notice Required — Insights.md"
        other.write_text(
            "---\ndate: 2026-10-02\npeople:\n  - \"[[Rachel]]\"\n  - \"[[Joel]]\"\n---\n"
            "## Summary\n\nRenewal talk.\n",
            encoding="utf-8",
        )
        event = {
            "title": "X Social Listening/GrokBot discussion",
            "people": [
                {"name": "Rachel Anderson", "email": "rachel.anderson@virtualpbx.com"},
                {"name": "joel.berk@virtualpbx.com", "email": "joel.berk@virtualpbx.com"},
            ],
        }
        found = self.mod.find_past(event)
        self.assertEqual([path.name for path, _why in found], [prior.name])


if __name__ == "__main__":
    unittest.main()
