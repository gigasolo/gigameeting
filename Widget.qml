import QtQuick
import QtMultimedia
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Bar control for Meeting Recorder. A click opens the card under the icon.
// The card is a quiet status readout. Opening it reads today's timed meetings
// from HEY. The one happening now, or starting within 15 minutes, can be
// joined and recorded. Later rows can be prepped. They do not start a
// recording. If HEY cannot be reached, OmaCal still offers that one meeting.
// History turns the body over to recent recordings. Play plays one recording
// in the card. Transcript and Insights open the note, and the next link is
// not stuck behind the first. After a take finishes, the saved default action
// is the button; the menu runs another action or changes the default. The
// card closes from the bar icon.
BarWidget {
  id: root
  moduleName: "gigasolo.gigameeting"

  readonly property int maxTitleLength: 200
  readonly property string helper: {
    var path = Qt.resolvedUrl("meeting-bar").toString()
    if (path.indexOf("file://") === 0) path = decodeURIComponent(path.slice(7))
    return path
  }

  property string recorderState: "off"
  property int elapsed: 0
  property real progress: 0
  property string title: ""

  property string pendingFolder: ""
  property string pendingTitle: ""
  property string armedTitle: ""
  property string offerTitle: ""
  property string offerWhen: ""
  property string offerUrl: ""
  property string offerId: ""
  property bool offerHasUrl: false
  property string daySource: ""
  property var dayEvents: []
  property var laterEvents: []
  property string briefUrl: ""
  property bool showingHistory: false
  property var recentMeetings: []
  property int recentSerial: 0
  property int recentRunSerial: 0
  property string recentOutput: ""
  property int pieceSerial: 0
  property int pieceRunSerial: 0
  property string pieceId: ""
  property string pieceKind: ""
  property string pieceOutput: ""
  property bool pieceBusy: false
  property string playId: ""
  property string audioId: ""
  property int audioSerial: 0
  property int audioRunSerial: 0
  property string audioText: ""
  property bool audioBusy: false
  property bool preparing: false
  property int prepSerial: 0
  property int prepRunSerial: 0
  property string prepId: ""
  property string prepOutput: ""
  property int daySerial: 0
  property string captureTitle: ""
  property int latestTries: 0
  property string statusLine: ""
  property bool starting: false
  property bool acting: false
  property var actions: []
  property string savedDefault: ""
  property bool queryBusy: false
  property bool queryActions: false
  property bool queryDay: false
  property bool queryOffer: false
  property bool queryLatest: false
  property bool menuOpen: false

  readonly property string defaultAction: {
    if (actions.length === 0) return ""
    for (var i = 0; i < actions.length; i++) {
      if (actions[i] === savedDefault) return savedDefault
    }
    return actions[0]
  }

  property var controlArgs: ["start"]
  property var controlCallback: null
  property string controlOutput: ""
  property var queryArgs: ["actions"]
  property var queryCallback: null
  property string queryOutput: ""

  readonly property bool live: recorderState === "recording" || recorderState === "paused"
                              || recorderState === "stopping" || recorderState === "transcribing"
  readonly property bool pending: pendingFolder !== ""
  readonly property bool ready: recorderState === "off" || recorderState === "idle" || recorderState === "done"
  readonly property bool canFlip: ready && !starting && !acting && !pending
  property bool flipSnap: false
  onCanFlipChanged: {
    if (!root.canFlip) {
      root.flipSnap = true
      root.showingHistory = false
      Qt.callLater(function() { root.flipSnap = false })
    }
  }
  onShowingHistoryChanged: if (root.showingHistory && root.panelOpen) root.refreshRecent()
  readonly property color foreground: bar ? bar.barForeground : Color.foreground
  readonly property color recordColor: Color.urgent
  property bool panelOpen: false
  property bool popoutSwitchClosing: false
  readonly property bool opened: panelOpen

  readonly property string faceFont: bar ? bar.fontFamily : Style.font.family
  property real micLevel: 0
  property real computerLevel: 0
  readonly property bool showClock: recorderState === "recording" || recorderState === "paused"
                                    || recorderState === "stopping" || recorderState === "transcribing"
  readonly property string deckDigits: showClock ? clock(elapsed) : "00:00"
  readonly property string statusText: {
    if (statusLine) return statusLine
    if (starting) return "Starting"
    if (recorderState === "recording") return "Recording"
    if (recorderState === "paused") return "Paused"
    if (recorderState === "stopping") return "Saving"
    if (recorderState === "transcribing") return "Transcribing " + Math.round(progress * 100) + "%"
    return "Ready"
  }
  readonly property string meetingLabel: {
    if (live && armedTitle) return armedTitle
    if (live && title) return title
    if (pending && ready && pendingTitle) return pendingTitle
    return ""
  }
  readonly property bool offerVisible: ready && !starting && !acting && !pending && offerTitle !== ""
  readonly property bool scheduleVisible: ready && !starting && !acting && !pending
                                         && (offerVisible || laterEvents.length > 0 || briefUrl !== "")
  readonly property string tooltip: {
    if (recorderState === "recording") return "Recording · " + clock(elapsed) + (title ? " · " + title : "")
    if (recorderState === "paused") return "Paused · " + clock(elapsed) + (title ? " · " + title : "")
    if (recorderState === "stopping") return "Saving…"
    if (recorderState === "transcribing") return "Transcribing " + Math.round(progress * 100) + "%"
    return "GigaMeeting"
  }

  visible: true
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function level(value) {
    var n = Number(value)
    return isFinite(n) ? Math.max(0, Math.min(1, n)) : 0
  }

  function clock(secs) {
    var h = Math.floor(secs / 3600), m = Math.floor(secs / 60) % 60, s = secs % 60
    var mm = (m < 10 ? "0" : "") + m, ss = (s < 10 ? "0" : "") + s
    return h > 0 ? h + ":" + mm + ":" + ss : mm + ":" + ss
  }

  function apply(line) {
    if (line.length > 4096) return
    var data
    try { data = JSON.parse(line) } catch (e) { return }
    if (!data || typeof data.state !== "string") return

    var next = /^(off|idle|recording|paused|stopping|transcribing|done)$/.test(data.state) ? data.state : "off"
    var prev = root.recorderState
    root.elapsed = Math.max(0, Math.floor(Number(data.elapsed) || 0))
    root.progress = root.level(data.progress)
    root.title = typeof data.title === "string" ? data.title.slice(0, root.maxTitleLength) : ""
    if (next === "recording") {
      root.micLevel = root.level(data.mic)
      root.computerLevel = root.level(data.computer)
    } else {
      root.micLevel = 0
      root.computerLevel = 0
    }
    root.recorderState = next
    var wasLive = prev === "recording" || prev === "paused" || prev === "stopping" || prev === "transcribing"
    var nowLive = next === "recording" || next === "paused" || next === "stopping" || next === "transcribing"
    if (!wasLive && nowLive) root.stopClip()
    if (wasLive && !nowLive) root.armedTitle = ""
    if (next === "recording" && root.statusLine === "Couldn't open the meeting link")
      root.statusLine = ""
    if (root.panelOpen && root.ready && prev !== next
        && prev !== "off" && prev !== "idle" && prev !== "done")
      root.refreshDay()

    if (next === "done" && prev !== "done"
        && (prev === "transcribing" || prev === "stopping" || prev === "recording" || prev === "paused")) {
      root.captureDone()
    }
  }

  function open() {
    root.panelOpen = true
    root.refreshActions()
    root.refreshDay()
    root.refreshRecent()
  }

  function close() {
    root.stopClip()
    root.prepSerial += 1
    root.recentSerial += 1
    root.pieceSerial += 1
    root.preparing = false
    root.flipSnap = true
    root.panelOpen = false
    root.showingHistory = false
    Qt.callLater(function() { root.flipSnap = false })
    root.recentMeetings = []
    root.recentOutput = ""
    root.pieceOutput = ""
    root.pieceBusy = false
    if (pieceProc.running) pieceProc.running = false
    root.offerTitle = ""
    root.offerWhen = ""
    root.offerUrl = ""
    root.offerId = ""
    root.offerHasUrl = false
    root.daySource = ""
    root.dayEvents = []
    root.laterEvents = []
    root.briefUrl = ""
  }

  function toggle() {
    if (root.opened) root.close()
    else root.open()
  }

  function closeForPopoutSwitch() {
    root.popoutSwitchClosing = true
    root.close()
    Qt.callLater(function() { root.popoutSwitchClosing = false })
  }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root, direction)
    return false
  }

  function runControl(args, done) {
    if (controlProc.running) return false
    root.controlCallback = done
    root.controlOutput = ""
    root.controlArgs = args
    Qt.callLater(function() { if (!controlProc.running) controlProc.running = true })
    return true
  }

  function pumpQuery() {
    if (root.queryBusy || queryProc.running) return
    var args = null
    var done = null
    if (root.queryActions) {
      root.queryActions = false
      args = ["actions"]
      done = function(code, text) { root.actionsReady(code, text) }
    } else if (root.queryDay) {
      root.queryDay = false
      var daySerial = root.daySerial
      args = ["day"]
      done = function(code, text) {
        if (daySerial !== root.daySerial) return
        root.dayReady(code, text)
      }
    } else if (root.queryOffer) {
      root.queryOffer = false
      var offerSerial = root.daySerial
      args = ["agenda"]
      done = function(code, text) {
        if (offerSerial !== root.daySerial || root.daySource === "hey") return
        root.offerReady(code, text)
      }
    } else if (root.queryLatest) {
      root.queryLatest = false
      args = ["latest", root.captureTitle]
      done = function(code, text) { root.latestReady(code, text) }
    } else {
      return
    }
    root.queryBusy = true
    root.queryCallback = done
    root.queryOutput = ""
    root.queryArgs = args
    Qt.callLater(function() { if (!queryProc.running) queryProc.running = true })
  }

  function startRecording(name) {
    if (root.starting || root.acting) return
    root.stopClip()
    var notice = root.statusLine
    root.armedTitle = name || ""
    root.starting = true
    if (notice.indexOf("Couldn't open") !== 0) root.statusLine = ""
    var args = name ? ["start", name] : ["start"]
    if (!root.runControl(args, function(code, text) {
      root.starting = false
      var line = String(text || "").trim().split("\n")[0] || ""
      if (line === "recovery") {
        root.armedTitle = ""
        root.statusLine = "Unfinished recording. Choose Save, Later, or Discard in the app."
        root.open()
      } else if (code !== 0 || line.indexOf("failed") === 0) {
        root.armedTitle = ""
        root.statusLine = line || "Could not start recording"
        root.open()
      }
    })) {
      root.starting = false
      root.armedTitle = ""
      root.statusLine = "Could not start recording"
    }
  }

  function joinOffer() {
    if (root.starting || root.acting || root.preparing || !root.ready || !root.offerTitle) return
    var title = root.offerTitle
    if (root.daySource === "hey") {
      if (!root.offerHasUrl || !root.offerId) {
        root.startRecording(title)
        return
      }
      root.starting = true
      var heyCode = 0
      var heyBegin = function() {
        root.starting = false
        if (heyCode !== 0) root.statusLine = "Couldn't open the meeting link"
        Qt.callLater(function() { root.startRecording(title) })
      }
      if (!root.runControl(["open-event", root.offerId], function(exitCode) {
        heyCode = exitCode
        heyBegin()
      })) {
        heyCode = 1
        heyBegin()
      }
      return
    }
    var url = root.offerUrl
    if (!url) {
      root.startRecording(title)
      return
    }
    root.starting = true
    var openCode = 0
    var begin = function() {
      root.starting = false
      if (openCode !== 0) root.statusLine = "Couldn't open the meeting link"
      Qt.callLater(function() { root.startRecording(title) })
    }
    if (!root.runControl(["open", url], function(exitCode) {
      openCode = exitCode
      begin()
    })) {
      openCode = 1
      begin()
    }
  }

  function refreshDay() {
    if (!root.panelOpen || !root.ready) return
    root.daySerial += 1
    root.queryOffer = false
    root.queryDay = true
    root.pumpQuery()
  }

  function refreshAgenda() {
    if (!root.panelOpen || !root.ready || root.daySource === "hey") return
    root.queryOffer = true
    root.pumpQuery()
  }

  function pickOffer() {
    if (root.daySource !== "hey") return
    var now = Date.now()
    var windowMs = 15 * 60 * 1000
    var events = root.dayEvents || []
    var current = []
    var soon = []
    var rest = []
    for (var i = 0; i < events.length; i++) {
      var ev = events[i]
      if (!ev || ev.end <= now) continue
      rest.push(ev)
      if (ev.start <= now) current.push(ev)
      else if (ev.start - now <= windowMs) soon.push(ev)
    }
    var chosen = null
    if (current.length) {
      current.sort(function(a, b) {
        var link = (a.hasUrl ? 1 : 0) - (b.hasUrl ? 1 : 0)
        return link !== 0 ? link : a.start - b.start
      })
      chosen = current[current.length - 1]
    } else if (soon.length) {
      soon.sort(function(a, b) { return a.start - b.start })
      chosen = soon[0]
    }
    if (chosen) {
      root.offerId = String(chosen.id || "")
      root.offerTitle = String(chosen.title || "").slice(0, root.maxTitleLength)
      root.offerWhen = String(chosen.when || "").slice(0, 40)
      root.offerHasUrl = chosen.hasUrl === true
      root.offerUrl = ""
    } else {
      root.offerId = ""
      root.offerTitle = ""
      root.offerWhen = ""
      root.offerHasUrl = false
      root.offerUrl = ""
    }
    rest.sort(function(a, b) { return a.start - b.start })
    var rows = []
    for (var j = 0; j < rest.length; j++) {
      if (chosen && rest[j].id === chosen.id) continue
      rows.push(rest[j])
      if (rows.length >= 4) break
    }
    root.laterEvents = rows
  }

  function dayReady(code, text) {
    if (!root.ready) return
    var line = String(text || "").trim().split("\n")[0] || ""
    if (!line) return
    var data
    try { data = JSON.parse(line) } catch (e) { return }
    if (!data || (data.source !== "hey" && data.source !== "omacal")) return
    if (data.source === "hey") {
      var events = data.events || []
      var cleaned = []
      var count = events.length !== undefined ? events.length : 8
      for (var i = 0; i < count; i++) {
        var ev = events[i]
        if (!ev) break
        var title = typeof ev.title === "string" ? ev.title.trim() : ""
        var start = Number(ev.start)
        var end = Number(ev.end)
        if (!title || !isFinite(start) || !isFinite(end)) continue
        cleaned.push({
          id: String(ev.id || ""),
          title: title.slice(0, root.maxTitleLength),
          when: typeof ev.when === "string" ? ev.when.slice(0, 40) : "",
          start: start,
          end: end,
          hasUrl: ev.hasUrl === true
        })
      }
      root.daySource = "hey"
      root.dayEvents = cleaned
      root.pickOffer()
      return
    }
    root.daySource = "omacal"
    root.dayEvents = []
    root.laterEvents = []
    root.offerId = ""
    root.offerHasUrl = false
    root.applyOffer(data.offer || null)
  }

  function applyOffer(data) {
    if (!data) {
      root.offerTitle = ""
      root.offerWhen = ""
      root.offerUrl = ""
      return
    }
    var title = typeof data.title === "string" ? data.title.trim() : ""
    var url = typeof data.url === "string" ? data.url : ""
    if (url.indexOf("https://") !== 0 && url.indexOf("http://") !== 0) url = ""
    root.offerTitle = title.slice(0, root.maxTitleLength)
    root.offerWhen = typeof data.when === "string" ? data.when.slice(0, 40) : ""
    root.offerUrl = url.slice(0, 2000)
  }

  function offerReady(code, text) {
    if (!root.ready || root.daySource === "hey") return
    var line = String(text || "").trim().split("\n")[0] || ""
    if (!line) {
      root.applyOffer(null)
      return
    }
    var data
    try { data = JSON.parse(line) } catch (e) {
      root.applyOffer(null)
      return
    }
    root.daySource = "omacal"
    root.dayEvents = []
    root.laterEvents = []
    root.offerId = ""
    root.offerHasUrl = false
    root.applyOffer(data)
  }

  function prepare(id) {
    if (!id || root.preparing || prepProc.running || root.acting || root.starting || !root.ready) return
    root.prepSerial += 1
    root.prepRunSerial = root.prepSerial
    root.preparing = true
    root.briefUrl = ""
    root.statusLine = "Preparing…"
    root.prepOutput = ""
    root.prepId = id
    Qt.callLater(function() { if (!prepProc.running) prepProc.running = true })
  }

  function openBrief() {
    if (!root.briefUrl || root.briefUrl.indexOf("obsidian://open?") !== 0) return
    root.runControl(["open-note", root.briefUrl], function(code) {
      if (code !== 0) root.statusLine = "Couldn't open the brief"
    })
  }

  function refreshRecent() {
    if (!root.panelOpen || recentProc.running) return
    root.recentSerial += 1
    root.recentRunSerial = root.recentSerial
    root.recentOutput = ""
    Qt.callLater(function() { if (!recentProc.running) recentProc.running = true })
  }

  function recentReady(code, text) {
    var line = String(text || "").trim().split("\n")[0] || ""
    var data
    try { data = JSON.parse(line) } catch (e) {
      root.recentMeetings = []
      return
    }
    if (code !== 0 || !data || data.meetings === undefined || data.meetings.length === undefined) {
      root.recentMeetings = []
      return
    }
    var clean = []
    var count = Math.min(data.meetings.length, 6)
    for (var i = 0; i < count; i++) {
      var row = data.meetings[i]
      if (!row) continue
      var id = typeof row.id === "string" ? row.id : ""
      if (!id || id.length > 180 || id.indexOf("/") >= 0 || id.indexOf("\\") >= 0 || id.indexOf("..") >= 0)
        continue
      var title = typeof row.title === "string" ? row.title : ""
      var day = typeof row.day === "string" ? row.day : ""
      var time = typeof row.time === "string" ? row.time : ""
      clean.push({
        id: id,
        title: title.slice(0, 120) || "Meeting",
        day: day.slice(0, 32),
        time: time.slice(0, 8),
        recording: row.recording === true,
        transcript: row.transcript === true,
        insights: row.insights === true
      })
    }
    root.recentMeetings = clean
  }

  function fileUrl(path) {
    if (typeof path !== "string" || path.charAt(0) !== "/") return ""
    var parts = path.split("/")
    var encoded = []
    for (var i = 0; i < parts.length; i++) {
      if (parts[i] === "..") return ""
      encoded.push(encodeURIComponent(parts[i]))
    }
    return "file://" + encoded.join("/")
  }

  function stopClip() {
    root.audioSerial += 1
    root.audioBusy = false
    root.playId = ""
    root.audioId = ""
    root.audioText = ""
    if (audioProc.running) audioProc.running = false
    clip.stop()
    clip.source = ""
  }

  function toggleClip(id) {
    if (!root.panelOpen || !id || root.live) return
    var mine = root.playId === id && !root.audioBusy && String(clip.source) !== ""
    if (mine && clip.playbackState === MediaPlayer.PlayingState) {
      clip.pause()
      return
    }
    if (mine) {
      if (clip.duration > 0 && clip.position >= clip.duration - 500)
        clip.position = 0
      clip.play()
      return
    }
    root.audioSerial += 1
    root.audioRunSerial = root.audioSerial
    root.audioId = id
    root.playId = id
    root.audioText = ""
    root.audioBusy = true
    clip.stop()
    clip.source = ""
    if (audioProc.running) return
    Qt.callLater(function() {
      if (!audioProc.running && root.audioBusy && root.audioRunSerial === root.audioSerial)
        audioProc.running = true
    })
  }

  function openPiece(id, kind) {
    if (!root.panelOpen || !id || root.pieceBusy || pieceProc.running) return
    if (kind !== "transcript" && kind !== "insights") return
    root.pieceBusy = true
    root.pieceSerial += 1
    root.pieceRunSerial = root.pieceSerial
    root.pieceOutput = ""
    root.pieceId = id
    root.pieceKind = kind
    Qt.callLater(function() { if (!pieceProc.running) pieceProc.running = true })
  }

  function pauseRecording() {
    root.runControl(["pause"], function(code, text) {
      if (code !== 0) root.statusLine = String(text || "").trim() || "Could not pause"
    })
  }

  function stopRecording() {
    root.runControl(["stop"], function(code, text) {
      if (code !== 0) root.statusLine = String(text || "").trim() || "Could not stop"
    })
  }

  function openRecorder() {
    Quickshell.execDetached(["omarchy-meeting-recorder"])
  }

  function refreshActions() {
    root.queryActions = true
    root.pumpQuery()
  }

  function actionsReady(code, text) {
    var lines = String(text || "").split("\n")
    var names = []
    for (var i = 0; i < lines.length; i++) {
      var name = lines[i].trim()
      if (name) names.push(name)
    }
    root.actions = names
  }

  function captureDone() {
    root.captureTitle = root.title
    root.latestTries = 0
    root.pendingFolder = ""
    root.resolveLatest()
  }

  function resolveLatest() {
    root.queryLatest = true
    root.pumpQuery()
  }

  function latestReady(code, text) {
    var path = String(text || "").trim().split("\n")[0] || ""
    if (path) {
      root.pendingFolder = path
      root.pendingTitle = root.captureTitle || root.title
      return
    }
    root.latestTries += 1
    if (root.latestTries < 8) latestTimer.restart()
    else root.statusLine = "Couldn't find the meeting folder"
  }

  function runAction(name) {
    if (!root.pendingFolder || root.acting) return
    root.acting = true
    root.statusLine = "Running " + name + "…"
    root.runControl(["run", name, root.pendingFolder], function(code, text) {
      root.acting = false
      var lines = String(text || "").trim().split("\n")
      var last = lines.length ? lines[lines.length - 1] : ""
      if (code === 0) {
        root.pendingFolder = ""
        root.pendingTitle = ""
        root.statusLine = ""
      } else {
        root.statusLine = last || "Action failed"
      }
    })
  }

  function setDefaultAction(name) {
    if (!name) return
    root.savedDefault = name
    defaultFile.setText(name + "\n")
  }

  FileView {
    id: defaultFile
    path: Quickshell.env("HOME") + "/.local/state/omarchy/gigameeting-default-action"
    watchChanges: true
    atomicWrites: true
    printErrors: false
    onLoaded: root.savedDefault = String(text() || "").trim()
  }

  Process {
    id: watcher
    running: true
    command: ["omarchy-meeting-recorder", "watch"]
    stdout: SplitParser {
      onRead: function(line) { root.apply(line) }
    }
  }

  Timer {
    interval: 5000
    running: !watcher.running
    repeat: true
    onTriggered: watcher.running = true
  }

  Timer {
    id: latestTimer
    interval: 1000
    onTriggered: root.resolveLatest()
  }

  Timer {
    id: offerTimer
    interval: 60000
    repeat: true
    running: root.panelOpen && root.ready && !root.starting && !root.pending
    onTriggered: {
      if (root.daySource === "hey") root.pickOffer()
      else root.refreshAgenda()
    }
  }

  Process {
    id: recentProc
    command: [root.helper, "recent"]
    stdout: SplitParser { onRead: function(line) { root.recentOutput += line + "\n" } }
    onExited: function(code) {
      var serial = root.recentRunSerial
      var text = root.recentOutput
      root.recentOutput = ""
      if (serial !== root.recentSerial || !root.panelOpen) return
      root.recentReady(code, text)
    }
  }

  Process {
    id: pieceProc
    command: [root.helper, "open-recent", root.pieceId, root.pieceKind]
    stdout: SplitParser { onRead: function(line) { root.pieceOutput += line + "\n" } }
    stderr: SplitParser { onRead: function(line) { root.pieceOutput += line + "\n" } }
    onExited: function(code) {
      var serial = root.pieceRunSerial
      var kind = root.pieceKind
      root.pieceOutput = ""
      root.pieceBusy = false
      if (serial !== root.pieceSerial || !root.panelOpen) return
      if (code === 0) {
        if (root.statusLine.indexOf("Couldn't open the ") === 0) root.statusLine = ""
        return
      }
      root.statusLine = kind === "insights" ? "Couldn't open the insights" : "Couldn't open the transcript"
    }
  }

  MediaPlayer {
    id: clip
    audioOutput: AudioOutput {}
    onErrorOccurred: function(error, errorString) {
      if (!root.panelOpen || root.audioBusy || root.playId === "" || error === MediaPlayer.NoError) return
      if (String(clip.source) === "") return
      root.playId = ""
      root.statusLine = "Couldn't play the recording"
      clip.stop()
    }
  }

  Process {
    id: audioProc
    command: [root.helper, "audio", root.audioId]
    stdout: SplitParser { onRead: function(line) { root.audioText += line + "\n" } }
    onExited: function(code) {
      var serial = root.audioRunSerial
      var text = root.audioText
      root.audioText = ""
      if (serial !== root.audioSerial || !root.panelOpen) {
        if (root.audioBusy && root.panelOpen && root.audioRunSerial === root.audioSerial) {
          Qt.callLater(function() {
            if (!audioProc.running && root.audioBusy && root.audioRunSerial === root.audioSerial)
              audioProc.running = true
          })
        }
        return
      }
      root.audioBusy = false
      var path = String(text || "").trim().split("\n")[0] || ""
      var url = code === 0 ? root.fileUrl(path) : ""
      if (!url) {
        root.playId = ""
        root.statusLine = "Couldn't play the recording"
        return
      }
      if (root.statusLine === "Couldn't play the recording") root.statusLine = ""
      clip.source = url
      clip.play()
    }
  }

  Process {
    id: prepProc
    command: [root.helper, "prep", root.prepId]
    stdout: SplitParser { onRead: function(line) { root.prepOutput += line + "\n" } }
    onExited: function(code) {
      var serial = root.prepRunSerial
      var text = root.prepOutput
      root.prepOutput = ""
      if (serial !== root.prepSerial) return
      root.preparing = false
      var lines = String(text || "").trim().split("\n")
      var last = lines.length ? lines[lines.length - 1] : ""
      if (code === 0 && last.indexOf("ready obsidian://open?") === 0) {
        root.briefUrl = last.slice(6).trim()
        root.statusLine = ""
      } else {
        root.briefUrl = ""
        root.statusLine = "Couldn't prepare that meeting"
      }
    }
  }

  Process {
    id: controlProc
    command: [root.helper].concat(root.controlArgs)
    stdout: SplitParser { onRead: function(line) { root.controlOutput += line + "\n" } }
    stderr: SplitParser { onRead: function(line) { root.controlOutput += line + "\n" } }
    onExited: function(code) {
      var text = root.controlOutput
      var done = root.controlCallback
      root.controlCallback = null
      if (done) done(code, text)
    }
  }

  Process {
    id: queryProc
    command: [root.helper].concat(root.queryArgs)
    stdout: SplitParser { onRead: function(line) { root.queryOutput += line + "\n" } }
    stderr: SplitParser { onRead: function(line) { root.queryOutput += line + "\n" } }
    onExited: function(code) {
      var text = root.queryOutput
      var done = root.queryCallback
      root.queryCallback = null
      root.queryBusy = false
      if (done) done(code, text)
      Qt.callLater(function() { root.pumpQuery() })
    }
  }

  component DocLink: Text {
    id: link
    property string meetingId: ""
    property string kind: ""
    property bool available: false

    visible: available
    width: visible ? implicitWidth : 0
    textFormat: Text.PlainText
    color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, area.pressed ? 1 : 0.78)
    font.family: root.faceFont
    font.pixelSize: Style.font.caption
    font.underline: area.containsMouse
    opacity: root.pieceBusy ? 0.4 : 1

    MouseArea {
      id: area
      anchors.fill: parent
      hoverEnabled: true
      enabled: !root.pieceBusy
      cursorShape: containsMouse ? Qt.PointingHandCursor : Qt.ArrowCursor
      onClicked: root.openPiece(link.meetingId, link.kind)
    }
  }

  component PlayLink: Text {
    id: play
    property string meetingId: ""
    property bool available: false
    readonly property bool active: meetingId !== "" && root.playId === meetingId
    readonly property bool playing: active && clip.playbackState === MediaPlayer.PlayingState

    visible: available
    width: visible ? implicitWidth : 0
    textFormat: Text.PlainText
    text: playing ? "Pause" : "Play"
    color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, area.pressed ? 1 : 0.78)
    font.family: root.faceFont
    font.pixelSize: Style.font.caption
    font.underline: area.containsMouse
    opacity: active && root.audioBusy ? 0.4 : 1

    MouseArea {
      id: area
      anchors.fill: parent
      hoverEnabled: true
      enabled: !(play.active && root.audioBusy)
      cursorShape: containsMouse ? Qt.PointingHandCursor : Qt.ArrowCursor
      onClicked: root.toggleClip(play.meetingId)
    }
  }

  component WordButton: Button {
    property bool live: false
    property bool strong: false

    enabled: live
    opacity: live ? 1 : 0.38
    active: live && strong
    foreground: root.foreground
    fontFamily: root.faceFont
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    tooltipText: root.tooltip
    iconComponent: Component {
      Item {
        implicitWidth: Style.bar.iconCanvas
        implicitHeight: Style.bar.iconCanvas
        MeetingMark {
          anchors.centerIn: parent
          iconSize: Style.bar.iconCanvas
          color: root.foreground
          discColor: root.recorderState === "paused"
                     ? Qt.rgba(root.recordColor.r, root.recordColor.g, root.recordColor.b, 0.4)
                     : root.recordColor
          discFilled: root.recorderState === "recording" || root.recorderState === "paused"
          pulsing: root.recorderState === "recording"
        }
      }
    }
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.LeftButton) root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    onOpenChanged: if (!open) root.menuOpen = false
    centerOnBar: false
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(360))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Column {
        id: column
        width: parent.width
        spacing: Style.space(12)

        Item {
          id: header
          width: parent.width
          implicitHeight: Math.max(heroMark.implicitHeight, heroLabels.implicitHeight, faceButton.implicitHeight, openButton.implicitHeight)

          MeetingMark {
            id: heroMark
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            iconSize: Style.font.display
            color: root.foreground
            discColor: root.recorderState === "paused"
                       ? Qt.rgba(root.recordColor.r, root.recordColor.g, root.recordColor.b, 0.4)
                       : root.recordColor
            discFilled: root.recorderState === "recording" || root.recorderState === "paused"
          }

          Column {
            id: heroLabels
            anchors.left: heroMark.right
            anchors.leftMargin: Style.space(14)
            anchors.right: faceButton.left
            anchors.rightMargin: Style.space(12)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)

            Text {
              textFormat: Text.PlainText
              text: "GigaMeeting"
              color: root.foreground
              font.family: root.faceFont
              font.pixelSize: Style.font.title
              font.bold: true
            }

            Item {
              width: parent.width
              implicitHeight: statusLabel.implicitHeight

              Rectangle {
                id: statusDot
                visible: root.recorderState === "recording"
                width: 6
                height: 6
                radius: 3
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.topMargin: Math.max(0, (statusLabel.font.pixelSize - height) / 2)
                color: root.recordColor

                SequentialAnimation on opacity {
                  running: statusDot.visible
                  loops: Animation.Infinite
                  alwaysRunToEnd: true
                  NumberAnimation { to: 0.35; duration: 700; easing.type: Easing.InOutSine }
                  NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine }
                  onRunningChanged: if (!running) statusDot.opacity = 1
                }
              }

              Text {
                id: statusLabel
                anchors.left: parent.left
                anchors.leftMargin: statusDot.visible ? statusDot.width + Style.space(6) : 0
                anchors.right: parent.right
                wrapMode: Text.WordWrap
                textFormat: Text.PlainText
                text: root.statusText
                color: root.statusLine !== ""
                       ? root.foreground
                       : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.62)
                font.family: root.faceFont
                font.pixelSize: Style.font.caption
              }
            }
          }

          Button {
            id: faceButton
            anchors.right: openButton.left
            anchors.rightMargin: visible ? Style.space(6) : 0
            anchors.verticalCenter: parent.verticalCenter
            visible: root.canFlip
            width: visible ? implicitWidth : 0
            text: root.showingHistory ? "Today" : "History"
            foreground: root.foreground
            fontFamily: root.faceFont
            onClicked: if (root.canFlip) root.showingHistory = !root.showingHistory
          }

          Button {
            id: openButton
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: "Open"
            foreground: root.foreground
            fontFamily: root.faceFont
            onClicked: root.openRecorder()
          }
        }

        Item {
          id: book
          width: parent.width
          height: todayFace.implicitHeight
          state: root.showingHistory ? "back" : "front"

          states: [
            State {
              name: "front"
              PropertyChanges { target: book; height: todayFace.implicitHeight }
              PropertyChanges { target: bookTurn; angle: 0 }
            },
            State {
              name: "back"
              PropertyChanges { target: book; height: historyFace.implicitHeight }
              PropertyChanges { target: bookTurn; angle: 180 }
            }
          ]

          transitions: Transition {
            NumberAnimation {
              properties: "height,angle"
              duration: root.flipSnap ? 0 : 480
              easing.type: Easing.InOutCubic
            }
          }

          transform: Rotation {
            id: bookTurn
            origin.x: book.width / 2
            origin.y: book.height / 2
            axis { x: 0; y: 1; z: 0 }
            angle: 0
          }

          Column {
            id: todayFace
            width: book.width
            height: implicitHeight
            spacing: Style.space(12)
            opacity: bookTurn.angle < 90 ? 1 : 0
            enabled: bookTurn.angle < 90

        Readout {
          width: parent.width
          foreground: root.foreground
          fontFamily: root.faceFont
          digits: root.deckDigits
          label: root.meetingLabel
          showProgress: root.recorderState === "transcribing"
          progress: root.progress
          metersLive: root.recorderState === "recording"
          mic: root.micLevel
          sys: root.computerLevel
        }

        Column {
          width: parent.width
          spacing: Style.space(8)
          visible: root.scheduleVisible

          Item {
            width: parent.width
            visible: root.offerVisible
            implicitHeight: Math.max(offerCaption.implicitHeight, offerPrep.implicitHeight)

            Text {
              id: offerCaption
              anchors.left: parent.left
              anchors.right: offerPrep.left
              anchors.rightMargin: offerPrep.visible ? Style.space(8) : 0
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              text: root.offerWhen ? root.offerWhen + "  " + root.offerTitle : root.offerTitle
              elide: Text.ElideRight
              color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.72)
              font.family: root.faceFont
              font.pixelSize: Style.font.caption
            }

            Button {
              id: offerPrep
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              visible: root.daySource === "hey" && root.offerId !== ""
              width: visible ? implicitWidth : 0
              text: "Prep"
              foreground: root.foreground
              fontFamily: root.faceFont
              enabled: !root.preparing && !root.starting && !root.acting
              onClicked: root.prepare(root.offerId)
            }
          }

          Button {
            width: parent.width
            visible: root.offerVisible
            leftAlign: true
            text: (root.daySource === "hey" ? root.offerHasUrl : root.offerUrl !== "")
                  ? "Join and record"
                  : "Record this meeting"
            foreground: root.foreground
            fontFamily: root.faceFont
            enabled: !root.starting && !root.acting && !root.preparing
            onClicked: root.joinOffer()
          }

          Text {
            width: parent.width
            visible: root.offerVisible && root.laterEvents.length > 0
            textFormat: Text.PlainText
            text: "Later"
            color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.62)
            font.family: root.faceFont
            font.pixelSize: Style.font.caption
          }

          Repeater {
            model: root.laterEvents

            delegate: Item {
              required property var modelData
              width: parent.width
              implicitHeight: Math.max(laterCaption.implicitHeight, laterPrep.implicitHeight)

              Text {
                id: laterCaption
                anchors.left: parent.left
                anchors.right: laterPrep.left
                anchors.rightMargin: Style.space(8)
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: modelData.when ? modelData.when + "  " + modelData.title : modelData.title
                elide: Text.ElideRight
                color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.72)
                font.family: root.faceFont
                font.pixelSize: Style.font.caption
              }

              Button {
                id: laterPrep
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                text: "Prep"
                foreground: root.foreground
                fontFamily: root.faceFont
                enabled: !root.preparing && !root.starting && !root.acting && modelData.id !== ""
                onClicked: root.prepare(modelData.id)
              }
            }
          }

          Button {
            width: parent.width
            visible: root.briefUrl !== ""
            leftAlign: true
            text: "Open brief"
            foreground: root.foreground
            fontFamily: root.faceFont
            enabled: !root.starting && !root.acting && !root.preparing
            onClicked: root.openBrief()
          }
        }

        Row {
          id: transport
          width: parent.width
          spacing: Style.space(8)

          WordButton {
            width: (transport.width - transport.spacing * 3) / 4
            text: "Record"
            live: root.ready && !root.starting && !root.acting
            strong: true
            onClicked: root.startRecording("")
          }

          WordButton {
            width: (transport.width - transport.spacing * 3) / 4
            text: "Resume"
            live: root.recorderState === "paused" && !root.acting
            strong: true
            onClicked: root.pauseRecording()
          }

          WordButton {
            width: (transport.width - transport.spacing * 3) / 4
            text: "Pause"
            live: root.recorderState === "recording" && !root.acting
            onClicked: root.pauseRecording()
          }

          WordButton {
            width: (transport.width - transport.spacing * 3) / 4
            text: "Stop"
            live: (root.recorderState === "recording" || root.recorderState === "paused") && !root.acting
            onClicked: root.stopRecording()
          }
        }

        Column {
          width: parent.width
          spacing: Style.space(8)
          visible: root.pending && root.ready

          PanelSeparator { foreground: root.foreground }

          PanelSectionHeader {
            text: "Actions"
            foreground: root.foreground
            fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
          }

          Text {
            width: parent.width
            visible: root.pendingTitle !== ""
            textFormat: Text.PlainText
            text: root.pendingTitle
            color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.72)
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }

          Column {
            id: actionSplit
            width: parent.width
            spacing: Style.space(4)
            visible: root.actions.length > 0

            Item {
              width: parent.width
              implicitHeight: defaultActionButton.implicitHeight

              Button {
                id: defaultActionButton
                anchors.left: parent.left
                anchors.right: menuKey.left
                anchors.rightMargin: Style.space(6)
                leftAlign: true
                text: root.defaultAction
                foreground: root.foreground
                fontFamily: root.faceFont
                enabled: !root.acting && !root.starting
                onClicked: root.runAction(root.defaultAction)
              }

              Button {
                id: menuKey
                anchors.right: parent.right
                width: Style.space(36)
                iconText: "󰅀"
                iconRotation: root.menuOpen ? 180 : 0
                foreground: root.foreground
                fontFamily: root.faceFont
                enabled: !root.acting && !root.starting
                onClicked: root.menuOpen = !root.menuOpen
              }
            }

            Rectangle {
              width: parent.width
              visible: root.menuOpen
              implicitHeight: menuColumn.implicitHeight + Style.space(8)
              radius: 4
              color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.05)
              border.width: 1
              border.color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.28)

              Column {
                id: menuColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Style.space(4)
                spacing: Style.space(2)

                Repeater {
                  model: root.actions

                  delegate: Item {
                    required property string modelData
                    width: parent.width
                    height: Style.space(32)

                    readonly property bool isDefault: modelData === root.defaultAction

                    Rectangle {
                      anchors.fill: parent
                      radius: 3
                      color: isDefault
                             ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.08)
                             : "transparent"
                    }

                    Text {
                      anchors.left: parent.left
                      anchors.right: defaultMark.left
                      anchors.verticalCenter: parent.verticalCenter
                      anchors.leftMargin: Style.space(8)
                      anchors.rightMargin: Style.space(8)
                      textFormat: Text.PlainText
                      text: modelData
                      color: root.foreground
                      font.family: root.faceFont
                      font.pixelSize: Style.font.body
                      elide: Text.ElideRight
                    }

                    Text {
                      id: defaultMark
                      anchors.right: parent.right
                      anchors.verticalCenter: parent.verticalCenter
                      anchors.rightMargin: Style.space(8)
                      textFormat: Text.PlainText
                      text: isDefault ? "Default" : "Set default"
                      color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, isDefault ? 1 : 0.62)
                      font.family: root.faceFont
                      font.pixelSize: Style.font.caption
                      font.bold: true
                    }

                    MouseArea {
                      anchors.left: parent.left
                      anchors.right: defaultMark.left
                      anchors.top: parent.top
                      anchors.bottom: parent.bottom
                      enabled: !root.acting && !root.starting
                      onClicked: {
                        root.menuOpen = false
                        root.runAction(modelData)
                      }
                    }

                    MouseArea {
                      anchors.left: defaultMark.left
                      anchors.right: parent.right
                      anchors.top: parent.top
                      anchors.bottom: parent.bottom
                      anchors.leftMargin: -Style.space(6)
                      onClicked: {
                        if (!isDefault) root.setDefaultAction(modelData)
                        root.menuOpen = false
                      }
                    }
                  }
                }
              }
            }
          }

          Text {
            width: parent.width
            visible: root.actions.length === 0
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            text: "No actions in the Meeting Recorder config."
            color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.72)
            font.family: root.faceFont
            font.pixelSize: Style.font.body
          }
          }
        }

        Column {
          id: historyFace
          width: book.width
          height: implicitHeight
          spacing: Style.space(10)
          opacity: bookTurn.angle >= 90 ? 1 : 0
          enabled: bookTurn.angle >= 90
          transform: Rotation {
            origin.x: book.width / 2
            origin.y: book.height / 2
            axis { x: 0; y: 1; z: 0 }
            angle: 180
          }

          PanelSectionHeader {
            text: "Recent"
            foreground: root.foreground
            fontFamily: root.faceFont
          }

          Text {
            width: parent.width
            visible: root.recentMeetings.length === 0
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            text: recentProc.running ? "Looking up recordings" : "No recordings yet"
            color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.62)
            font.family: root.faceFont
            font.pixelSize: Style.font.caption
          }

          Repeater {
            model: root.recentMeetings

            delegate: Column {
              required property var modelData
              required property int index
              width: historyFace.width
              spacing: Style.space(8)

              readonly property string dayLabel: {
                var day = modelData.day || ""
                if (index === 0) return day
                var prev = root.recentMeetings[index - 1]
                if (!prev || prev.day !== day) return day
                return ""
              }

              PanelSeparator {
                visible: index > 0
                height: visible ? implicitHeight : 0
                foreground: root.foreground
              }

              Text {
                width: parent.width
                visible: dayLabel !== ""
                height: visible ? implicitHeight : 0
                textFormat: Text.PlainText
                text: dayLabel
                color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.62)
                font.family: root.faceFont
                font.pixelSize: Style.font.caption
                font.bold: true
              }

              Item {
                width: parent.width
                implicitHeight: detail.implicitHeight

                Text {
                  id: whenText
                  width: Style.space(44)
                  anchors.left: parent.left
                  anchors.top: detail.top
                  anchors.topMargin: Style.space(2)
                  textFormat: Text.PlainText
                  text: modelData.time
                  elide: Text.ElideRight
                  color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.62)
                  font.family: root.faceFont
                  font.pixelSize: Style.font.caption
                }

                Column {
                  id: detail
                  anchors.left: whenText.right
                  anchors.right: parent.right
                  anchors.leftMargin: Style.space(8)
                  spacing: Style.space(3)

                  Text {
                    width: parent.width
                    textFormat: Text.PlainText
                    text: modelData.title
                    elide: Text.ElideRight
                    maximumLineCount: 1
                    color: root.foreground
                    font.family: root.faceFont
                    font.pixelSize: Style.font.body
                  }

                  Row {
                    spacing: Style.space(6)

                    PlayLink {
                      meetingId: modelData.id
                      available: modelData.recording === true
                    }

                    Text {
                      visible: modelData.recording === true && (modelData.transcript === true || modelData.insights === true)
                      textFormat: Text.PlainText
                      text: "·"
                      color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.35)
                      font.family: root.faceFont
                      font.pixelSize: Style.font.caption
                    }

                    DocLink {
                      meetingId: modelData.id
                      kind: "transcript"
                      available: modelData.transcript === true
                      text: "Transcript"
                    }

                    Text {
                      visible: modelData.transcript === true && modelData.insights === true
                      textFormat: Text.PlainText
                      text: "·"
                      color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.35)
                      font.family: root.faceFont
                      font.pixelSize: Style.font.caption
                    }

                    DocLink {
                      meetingId: modelData.id
                      kind: "insights"
                      available: modelData.insights === true
                      text: "Insights"
                    }
                  }

                  Item {
                    visible: root.playId === modelData.id && clip.duration > 0
                    width: parent.width
                    height: visible ? Style.space(10) : 0

                    Rectangle {
                      id: track
                      anchors.verticalCenter: parent.verticalCenter
                      width: parent.width
                      height: 2
                      radius: 1
                      color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.18)

                      Rectangle {
                        width: clip.duration > 0 ? track.width * Math.min(1, clip.position / clip.duration) : 0
                        height: parent.height
                        radius: 1
                        color: root.recordColor
                      }
                    }

                    MouseArea {
                      anchors.fill: parent
                      hoverEnabled: true
                      enabled: clip.duration > 0
                      cursorShape: enabled && containsMouse ? Qt.PointingHandCursor : Qt.ArrowCursor
                      onClicked: function(mouse) {
                        if (clip.duration > 0 && width > 0)
                          clip.position = Math.round(clip.duration * Math.max(0, Math.min(1, mouse.x / width)))
                      }
                    }
                  }
                }
              }
            }
          }
        }
        }
      }
    }
  }
}
