# GigaMeeting

GigaMeeting is a bar card for [Meeting Recorder](https://github.com/jankeesvw/omarchy-meeting-recorder). Click the icon to open the card. Record, pause, and stop live there. The icon click does not start a recording.

When a timed event is happening, or starts within 15 minutes, the card offers to join it and record it under that name. The time comes from OmaCal. All-day events are skipped. If nothing is due, the card stays Ready.

After a take this card watched finishes, the transcript can be sent through the actions in Meeting Recorder. One action is the button. The chevron lists the others and can set the default. Nothing runs by itself.

An independent [MIT](LICENSE)-licensed plugin by [GigaSolo](https://github.com/gigasolo) for [Omarchy](https://omarchy.org/).

## Install

```sh
omarchy plugin add https://github.com/gigasolo/gigameeting.git
```

Omarchy may ask which side of the bar to use. The default is the right.

Plugins run as unsandboxed code inside `omarchy-shell`. Read the source before enabling a plugin you do not already trust.

## Remove

```sh
omarchy plugin remove gigasolo.gigameeting
```

Removal leaves `~/.local/state/omarchy/gigameeting-default-action` in place. That file is only the name of the default action. Delete it if you do not want the choice remembered.

## Dependencies

Required:

- [omarchy-meeting-recorder](https://github.com/jankeesvw/omarchy-meeting-recorder)
- `python3`
- `xdg-open`
- `timeout` (from coreutils)

Optional:

- `omacal`, for the join offer. Without it, or with an empty calendar database, the offer is absent and Record still works.

Meeting Recorder actions are read from `~/.config/omarchy-meeting-recorder/config.toml` each time the card needs them.

## Marketplace

The shell lists this plugin under Audio. On the [Omarchy plugin marketplace](https://plugins.omarchy.org/publish.html) form, the category is Productivity and the tags are Bar and Quickshell.
