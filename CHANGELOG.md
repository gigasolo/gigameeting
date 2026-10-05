# Changelog

All notable changes to GigaMeeting are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Tomorrow's meetings, briefs that cite the source note, and a list that stays up while a recording or a prep is running. Version stays 1.1.0 until the next release.

### Added

- Tomorrow's timed meetings, under Tomorrow. The lookup stops there.
- A brief cites a sentence or two and links the insight or transcript. Earlier prep notes are not sources. A join link is not a description.
- When a brief exists, Brief replaces Prep and opens the note. The chevron preps again: the old note is removed, personal notes under My notes stay, and Brief shows Preparing while it runs. Closing the card leaves Preparing in place. Other meetings can be prepped at the same time.
- The list scrolls when it is taller than the card.

### Changed

- Later, Tomorrow, and History stay up during a recording, a transcription, a prep, and an action.
- Record and Join also start while the previous meeting is still being transcribed. They do not start a second recording over one that is already going.
- The vault is the one Obsidian has open. If none is open, it is `~/Documents/Obsidian`.

## [1.1.0] — 2026-10-04

Today's meetings on the card, and recent recordings you can play.

### Added

- Today's timed meetings from HEY. OmaCal lists that day when HEY cannot be reached.
- Later rows for the other meetings today. A row does not start a recording.
- Prep writes a short brief in the vault. Open brief jumps to it.
- History turns the card over to recent recordings. Play plays one in the card. Transcript and Insights open the note.
- `meeting-manage` files the transcript into Obsidian. Save to Obsidian runs it.

### Fixed

- History opens a note without the next link sticking.

## [1.0.1] — 2026-10-01

The action list survives opening the card.

### Added

- MIT license and the README.
- The listing says Meeting Recorder has to be installed first.

### Fixed

- Opening the card kept the action list. The calendar offer no longer replaces it, so Save still appears.
- Closing the card clears the join link.
- A finished title does not stick to the next take.
- A meeting folder has to stay inside `Documents/Meetings`.

## [1.0.0] — 2026-10-01

Record the meeting on the calendar from the bar.

### Added

- A bar card that starts, pauses, and stops Meeting Recorder.
- Join and record when OmaCal has a timed meeting happening now or starting within 15 minutes. The recording uses that meeting's name. All-day events are skipped.
- After a take this card watched finish, the Meeting Recorder action is the button. Nothing runs by itself.
