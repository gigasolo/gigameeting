#!/usr/bin/env python3
"""meeting-bar callers prints one app name, or nothing. It never records."""

from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

BAR = Path(__file__).resolve().parents[1] / "meeting-bar"


def node(node_id, name, klass, **props):
    body = {"node.name": name, "media.class": klass}
    body.update(props)
    return {"type": "PipeWire:Interface:Node", "id": node_id, "info": {"props": body}}


def callers(dump):
    env = os.environ.copy()
    env["CALLERS_DUMP"] = "1"
    done = subprocess.run(
        [str(BAR), "callers"],
        input=json.dumps(dump),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    return done.returncode, done.stdout, done.stderr


class CallersTests(unittest.TestCase):
    def test_zoom_playing_and_capturing(self):
        code, out, err = callers([
            node(1, "zoom-play", "Stream/Output/Audio", **{"application.name": "Zoom", "client.id": 9}),
            node(2, "zoom-rec", "Stream/Input/Audio", **{"application.name": "Zoom", "client.id": 9}),
        ])
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "Zoom\n")

    def test_music_only(self):
        code, out, err = callers([
            node(1, "spotify", "Stream/Output/Audio", **{"application.name": "Spotify", "client.id": 3}),
        ])
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "")

    def test_omavoice_and_meter_are_quiet(self):
        code, out, err = callers([
            node(1, "omavoice", "Audio/Source", **{"media.role": "Communication", "client.id": 1}),
            node(2, "omavoice.meter.hold", "Stream/Input/Audio", **{"client.id": 2}),
            node(3, "omavoice.aec", "Stream/Output/Audio", **{"media.role": "Communication", "client.id": 4}),
        ])
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "")

    def test_empty_graph(self):
        code, out, err = callers([])
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "")

    def test_communication_playback(self):
        code, out, err = callers([
            node(1, "meet", "Stream/Output/Audio", **{
                "application.name": "Google Meet",
                "media.role": "Communication",
                "client.id": 8,
            }),
        ])
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "Google Meet\n")


if __name__ == "__main__":
    unittest.main()
