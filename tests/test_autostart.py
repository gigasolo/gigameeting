#!/usr/bin/env python3
"""Decision tests for meeting-autostart.

The script has no .py suffix, so it is loaded by path. Nothing here runs the
recorder, hey, or omacal: time, events, and recorder state are passed in, and
the launcher is a list.
"""

from __future__ import annotations

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "meeting-autostart"

START = datetime(2026, 11, 11, 18, 0, tzinfo=timezone.utc).timestamp() * 1000
SECOND = 1000
MINUTE = 60 * SECOND
DAY = 24 * 60 * MINUTE


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def event(title: str = "Standup", start: float = START, ident: str = "41") -> dict:
    return {"id": ident, "title": title, "start": start, "end": start + 30 * MINUTE}


class AutostartTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.state = root / "state" / "autostart.json"
        # Before the load: the script reads the path once, at import.
        os.environ["GIGAMEETING_AUTOSTART_STATE"] = str(self.state)
        os.environ["OBSIDIAN_VAULT"] = str(root / "Obsidian")
        os.environ["OBSIDIAN_FOLDER"] = "Meetings"
        os.environ["GIGAMEETING_STATE"] = str(root / "day.json")
        os.environ["GIGAMEETING_ASK"] = "/bin/true"
        os.environ["MEETINGS_ROOT"] = str(root / "recordings")
        sys.modules.pop("gigameeting_autostart", None)
        loader = importlib.machinery.SourceFileLoader("gigameeting_autostart", str(SCRIPT))
        spec = importlib.util.spec_from_loader("gigameeting_autostart", loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        self.mod = module
        self.launched: list[tuple[list[str], str]] = []
        self.said: list[str] = []
        # A guard: no test may reach a real process. run_tick binds the real
        # detach as its default launcher, so the block sits under detach.
        for name in ("run", "Popen"):
            guard = mock.patch.object(
                module.subprocess, name, side_effect=AssertionError(f"real subprocess.{name}")
            )
            guard.start()
            self.addCleanup(guard.stop)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def tick(self, now_ms, events, state="idle", fired=None, can_wait=True, recovery=False):
        return self.mod.run_tick(
            now_ms,
            events,
            state,
            fired or {},
            can_wait=can_wait,
            recovery=recovery,
            launch=lambda argv, unit: self.launched.append((argv, unit)),
            say=self.said.append,
        )

    def verdicts(self, rows) -> list[str]:
        return [verdict for _, _, verdict in rows]

    # The fire window.

    def test_state_file_is_the_temp_one(self) -> None:
        self.assertEqual(self.mod.FIRED, self.state)

    def test_before_start_is_not_yet(self) -> None:
        fired, rows = self.tick(START - SECOND, [event()])
        self.assertEqual(self.verdicts(rows), ["not-yet"])
        self.assertEqual(fired, {})
        self.assertEqual(self.launched, [])

    def test_at_start_fires(self) -> None:
        fired, rows = self.tick(START, [event()])
        self.assertEqual(self.verdicts(rows), ["fire"])
        self.assertEqual(fired["41@%d" % START]["result"], "started")
        self.assertEqual(len(self.launched), 2)
        self.assertEqual(self.launched[0][0], self.mod.start_command("Standup"))
        self.assertEqual(self.launched[1][0], self.mod.wait_command())
        self.assertNotEqual(self.launched[0][1], self.launched[1][1])
        self.assertEqual(self.said, [])

    def test_inside_the_grace_fires(self) -> None:
        _, rows = self.tick(START + 90 * SECOND, [event()])
        self.assertEqual(self.verdicts(rows), ["fire"])
        self.assertEqual(len(self.launched), 2)

    def test_exactly_120_seconds_still_fires(self) -> None:
        self.assertEqual(self.mod.GRACE_MS, 120 * SECOND)
        self.assertEqual(self.mod.decide(event(), START + 120 * SECOND, {}, "idle"), "fire")
        self.assertEqual(self.mod.decide(event(), START + 120 * SECOND + 1, {}, "idle"), "late")

    def test_after_the_grace_is_late(self) -> None:
        fired, rows = self.tick(START + 3 * MINUTE, [event()])
        self.assertEqual(self.verdicts(rows), ["late"])
        self.assertEqual(fired, {})
        self.assertEqual(self.launched, [])

    def test_each_event_gets_its_own_verdict(self) -> None:
        events = [
            event("Earlier", START - 10 * MINUTE, "1"),
            event("Now", START, "2"),
            event("Soon", START + 10 * MINUTE, "3"),
        ]
        _, rows = self.tick(START, events)
        self.assertEqual(self.verdicts(rows), ["late", "fire", "not-yet"])
        self.assertEqual([argv for argv, _ in self.launched][0], self.mod.start_command("Now"))

    # Once only.

    def test_second_tick_does_not_fire_again(self) -> None:
        fired, _ = self.tick(START, [event()])
        self.launched.clear()
        again, rows = self.tick(START + MINUTE, [event()], "recording", fired)
        self.assertEqual(self.verdicts(rows), ["already-fired"])
        self.assertEqual(again, fired)
        self.assertEqual(self.launched, [])

    def test_stop_inside_the_window_does_not_fire_again(self) -> None:
        fired, _ = self.tick(START, [event()])
        fired, _ = self.tick(START + 30 * SECOND, [event()], "recording", fired)
        self.launched.clear()
        for state in ("idle", "transcribing", "done", "off"):
            fired, rows = self.tick(START + MINUTE, [event()], state, fired)
            self.assertEqual(self.verdicts(rows), ["already-fired"], state)
        self.assertEqual(self.launched, [])

    def test_fired_list_survives_the_file(self) -> None:
        fired, _ = self.tick(START, [event()])
        self.assertFalse(self.state.exists())
        self.mod.save_fired(fired)
        self.assertTrue(self.state.exists())
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)
        back = self.mod.read_fired()
        self.assertEqual(back, fired)
        self.launched.clear()
        _, rows = self.tick(START + MINUTE, [event()], "idle", back)
        self.assertEqual(self.verdicts(rows), ["already-fired"])
        self.assertEqual(self.launched, [])

    def test_read_fired_is_empty_without_a_usable_file(self) -> None:
        self.assertEqual(self.mod.read_fired(), {})
        self.state.parent.mkdir(parents=True)
        self.state.write_text("not json", encoding="utf-8")
        self.assertEqual(self.mod.read_fired(), {})
        self.state.write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(self.mod.read_fired(), {})

    def test_a_moved_event_is_a_new_event(self) -> None:
        fired, _ = self.tick(START, [event()])
        self.launched.clear()
        moved = event(start=START + MINUTE)
        _, rows = self.tick(START + MINUTE, [moved], "idle", fired)
        self.assertEqual(self.verdicts(rows), ["fire"])

    # All-day events.

    def test_all_day_hey_event_is_skipped(self) -> None:
        cal = self.mod.load_calendar()
        base = datetime.fromtimestamp(START / 1000, tz=timezone.utc)
        rows = [
            {
                "id": 7,
                "title": "Home",
                "all_day": True,
                "starts_at": stamp(base),
                "ends_at": stamp(base + timedelta(hours=1)),
            },
            {
                "id": 8,
                "title": "Standup",
                "starts_at": stamp(base),
                "ends_at": stamp(base + timedelta(minutes=30)),
            },
        ]
        asked: list[str] = []

        def fake_rows(day: str):
            asked.append(day)
            return rows

        def no_omacal(now_ms=None):
            raise AssertionError("omacal is the spare; HEY answered")

        with mock.patch.object(cal, "hey_rows", fake_rows), mock.patch.object(
            cal, "omacal_events", no_omacal
        ):
            source, events = self.mod.read_events(cal, START)
        self.assertEqual(source, "hey")
        self.assertEqual(len(asked), 1)
        self.assertEqual([item["title"] for item in events], ["Standup"])
        self.assertEqual(self.mod.event_key(events[0]), "8@%d" % START)

    def test_all_day_omacal_event_is_skipped(self) -> None:
        cal = self.mod.load_calendar()
        now_ms = time.time() * 1000
        start = int(now_ms)
        payload = {
            "ok": True,
            "data": [
                {
                    "title": "Holiday",
                    "allDay": True,
                    "startMs": start,
                    "endMs": start + DAY,
                    "start": "",
                    "end": "",
                },
                {
                    "title": "Standup",
                    "allDay": False,
                    "startMs": start,
                    "endMs": start + 30 * MINUTE,
                    "start": "",
                    "end": "",
                },
            ],
        }
        calls: list[list[str]] = []

        def fake_run(argv, **kwargs):
            calls.append(list(argv))
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

        # HEY is out, so the spare is read. Its own all-day filter runs for real;
        # only the omacal process under it is a fake.
        with mock.patch.object(cal, "hey_rows", lambda day: None), mock.patch.object(
            cal, "subprocess", SimpleNamespace(run=fake_run, TimeoutExpired=TimeoutError)
        ):
            source, events = self.mod.read_events(cal, now_ms)
        self.assertEqual(source, "omacal")
        self.assertEqual([argv[0] for argv in calls], ["omacal"])
        self.assertEqual([item["title"] for item in events], ["Standup"])
        self.assertEqual(events[0]["id"], "")
        self.assertEqual(self.mod.event_key(events[0]), "Standup@%d" % start)

    def test_omacal_is_the_spare_when_hey_is_out(self) -> None:
        cal = self.mod.load_calendar()
        spare = [{"id": "", "title": "Standup", "start": START, "end": START + MINUTE}]
        with mock.patch.object(cal, "hey_rows", lambda day: None), mock.patch.object(
            cal, "omacal_events", lambda now_ms=None: spare
        ):
            source, events = self.mod.read_events(cal, START)
        self.assertEqual(source, "omacal")
        self.assertEqual(events, spare)

    # The recorder is busy.

    def test_recording_and_paused_do_not_start_and_are_marked(self) -> None:
        for state in ("recording", "paused"):
            self.launched.clear()
            fired, rows = self.tick(START, [event()], state)
            self.assertEqual(self.verdicts(rows), ["recording"], state)
            self.assertEqual(self.launched, [], state)
            self.assertEqual(fired["41@%d" % START]["result"], "recording", state)
            # Stop, still inside the window: no new recording.
            _, rows = self.tick(START + MINUTE, [event()], "idle", fired)
            self.assertEqual(self.verdicts(rows), ["already-fired"], state)
            self.assertEqual(self.launched, [], state)

    def test_stopping_is_busy_and_not_marked(self) -> None:
        fired, rows = self.tick(START, [event()], "stopping")
        self.assertEqual(self.verdicts(rows), ["busy"])
        self.assertEqual(fired, {})
        self.assertEqual(self.launched, [])
        # The next tick, with the recorder free, may still start it.
        _, rows = self.tick(START + MINUTE, [event()], "transcribing", fired)
        self.assertEqual(self.verdicts(rows), ["fire"])
        self.assertEqual(len(self.launched), 2)

    def test_unfinished_recording_holds_the_start(self) -> None:
        fired, rows = self.tick(START, [event()], "off", recovery=True)
        self.assertEqual(self.verdicts(rows), ["recovery"])
        self.assertEqual(fired, {})
        self.assertEqual(self.launched, [])

    def test_off_without_recovery_fires(self) -> None:
        _, rows = self.tick(START, [event()], "off")
        self.assertEqual(self.verdicts(rows), ["fire"])
        self.assertEqual(len(self.launched), 2)

    def test_recovery_only_matters_when_the_recorder_is_off(self) -> None:
        _, rows = self.tick(START, [event()], "idle", recovery=True)
        self.assertEqual(self.verdicts(rows), ["fire"])

    # Keys, names, commands.

    def test_event_key_uses_the_id_then_the_title(self) -> None:
        self.assertEqual(self.mod.event_key(event()), "41@%d" % START)
        self.assertEqual(self.mod.event_key(event(ident="")), "Standup@%d" % START)
        self.assertEqual(
            self.mod.event_key({"title": "Standup", "start": START + 0.0}), "Standup@%d" % START
        )

    def test_omacal_events_fire_once_by_title_and_start(self) -> None:
        spare = event(ident="")
        fired, rows = self.tick(START, [spare])
        self.assertEqual(self.verdicts(rows), ["fire"])
        self.assertIn("Standup@%d" % START, fired)
        _, rows = self.tick(START + MINUTE, [spare], "idle", fired)
        self.assertEqual(self.verdicts(rows), ["already-fired"])

    def test_prune_drops_entries_older_than_two_days(self) -> None:
        now = START
        fired = {
            "fresh": {"start": now - MINUTE},
            "edge": {"start": now - 2 * DAY},
            "old": {"start": now - 2 * DAY - 1},
            "ancient": {"start": now - 30 * DAY},
            "junk": "yes",
            "no-start": {"title": "x"},
            "text-start": {"start": "today"},
        }
        self.assertEqual(sorted(self.mod.prune(fired, now)), ["edge", "fresh"])

    def test_safe_title(self) -> None:
        self.assertEqual(self.mod.safe_title("--name oops"), "name oops")
        self.assertEqual(self.mod.safe_title("-h"), "h")
        self.assertEqual(self.mod.safe_title("  Weekly \n sync  "), "Weekly sync")
        self.assertEqual(self.mod.safe_title("Q4 - plan"), "Q4 - plan")
        for blank in ("", "   ", "---", " - "):
            self.assertEqual(self.mod.safe_title(blank), "Meeting", repr(blank))

    def test_start_command_uses_a_positional_name(self) -> None:
        command = self.mod.start_command("--Design review")
        self.assertEqual(command, [self.mod.RECORDER, "start", "Design review"])
        self.assertFalse([word for word in command[1:] if word.startswith("-")])
        self.assertEqual(self.mod.start_command("")[2], "Meeting")

    def test_wait_script_waits_then_files_the_folder(self) -> None:
        script = self.mod.wait_script()
        self.assertIn(" wait)", script)
        self.assertIn('both "$folder"', script)
        self.assertLess(script.index(" wait)"), script.index('both "$folder"'))
        self.assertEqual(self.mod.wait_command(), ["bash", "-c", script])

    def test_without_wait_it_starts_and_says_so(self) -> None:
        fired, rows = self.tick(START, [event()], can_wait=False)
        self.assertEqual(self.verdicts(rows), ["fire"])
        self.assertEqual([argv for argv, _ in self.launched], [self.mod.start_command("Standup")])
        self.assertEqual(len(self.said), 1)
        self.assertIn("wait", self.said[0])
        self.assertEqual(fired["41@%d" % START]["result"], "started")

    def test_run_tick_leaves_the_given_fired_list_alone(self) -> None:
        given: dict = {}
        fired, _ = self.tick(START, [event()], fired=given)
        self.assertEqual(given, {})
        self.assertEqual(len(fired), 1)

    # main().

    def run_main(self, args, events, state="idle", can_wait=True, recovery=False):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(self.mod, "read_events", lambda cal, now_ms: ("hey", events))
            )
            stack.enter_context(mock.patch.object(self.mod, "recorder_state", lambda: state))
            stack.enter_context(mock.patch.object(self.mod, "supports_wait", lambda: can_wait))
            stack.enter_context(
                mock.patch.object(self.mod, "unfinished_recording", lambda: recovery)
            )
            stack.enter_context(mock.patch.object(self.mod, "FIRED", self.state))
            # main() launches through detach, which run_tick bound when the script
            # loaded. Patching the name would miss it, so catch the process call.
            self.spawned = stack.enter_context(mock.patch.object(self.mod.subprocess, "run"))
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            code = self.mod.main(["meeting-autostart", *args])
        return code, out.getvalue(), err.getvalue()

    def test_dry_run_prints_decisions_and_writes_nothing(self) -> None:
        events = [event("Standup", START, "41"), event("Review", START + 60 * MINUTE, "42")]
        code, out, _ = self.run_main(
            ["--dry-run", "--now", "2026-11-11T18:00:30Z"], events
        )
        self.assertEqual(code, 0)
        self.assertIn("calendar: hey, 2 timed event(s)", out)
        self.assertIn("recorder state: idle", out)
        self.assertIn("'Standup' [41@%d]: fire" % START, out)
        self.assertIn("'Review' [42@%d]: not-yet" % (START + 60 * MINUTE), out)
        self.assertIn("would run", out)
        self.assertIn(" start Standup", out)
        self.assertIn("both", out)
        self.assertIn("nothing started, nothing written", out)
        self.assertFalse(self.state.exists())
        self.assertFalse(self.state.parent.exists())
        self.spawned.assert_not_called()

    def test_dry_run_without_wait_notes_it(self) -> None:
        code, out, _ = self.run_main(
            ["--dry-run", "--now", "2026-11-11T18:00:00Z"], [event()], can_wait=False
        )
        self.assertEqual(code, 0)
        self.assertIn("`wait` supported: no", out)
        self.assertIn("note:", out)
        self.assertEqual(out.count("would run"), 1)
        self.assertFalse(self.state.exists())

    def test_dry_run_with_no_events(self) -> None:
        code, out, _ = self.run_main(["--dry-run"], [])
        self.assertEqual(code, 0)
        self.assertIn("nothing to do", out)
        self.assertFalse(self.state.exists())

    def test_now_needs_dry_run_and_a_time(self) -> None:
        for args in (
            ["--now", "2026-11-11T18:00:00Z"],
            ["--dry-run", "--now"],
            ["--dry-run", "--now", "soon"],
            ["--bogus"],
        ):
            code, _, err = self.run_main(args, [event()])
            self.assertEqual(code, 2, args)
            self.assertTrue(err.strip(), args)
        self.spawned.assert_not_called()
        self.assertFalse(self.state.exists())

    def test_real_tick_writes_the_fired_list_once(self) -> None:
        now = time.time() * 1000
        current = event(start=now - 30 * SECOND)
        code, out, _ = self.run_main([], [current])
        self.assertEqual(code, 0)
        self.assertIn("fire", out)
        self.assertEqual(self.spawned.call_count, 2)
        first, second = (call.args[0] for call in self.spawned.call_args_list)
        self.assertEqual(first[-3:], self.mod.start_command("Standup"))
        self.assertEqual(second[-3:], self.mod.wait_command())
        self.assertEqual(list(json.loads(self.state.read_text())), [self.mod.event_key(current)])
        code, out, _ = self.run_main([], [current])
        self.assertEqual(code, 0)
        self.spawned.assert_not_called()
        self.assertEqual(out, "")

    def test_unreadable_recorder_skips_the_tick(self) -> None:
        now = time.time() * 1000
        code, out, _ = self.run_main([], [event(start=now)], state="unknown")
        self.assertEqual(code, 0)
        self.assertIn("skipping", out)
        self.spawned.assert_not_called()
        self.assertFalse(self.state.exists())


if __name__ == "__main__":
    unittest.main()
