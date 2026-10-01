import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Bar control for Meeting Recorder. A click opens the card under the icon.
// The card is a quiet status readout. When a calendar meeting is happening,
// or starts within 15 minutes, the card offers to join it and record it.
// After a take finishes, the saved default action is the button; the menu
// runs another action or changes the default. The card closes from the bar icon.
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
  property string captureTitle: ""
  property int latestTries: 0
  property string statusLine: ""
  property bool starting: false
  property bool acting: false
  property var actions: []
  property string savedDefault: ""
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
    if (next === "recording" && root.statusLine === "Couldn't open the meeting link")
      root.statusLine = ""
    if (root.panelOpen && root.ready && prev !== next
        && prev !== "off" && prev !== "idle" && prev !== "done")
      root.refreshOffer()

    if (next === "done" && prev !== "done"
        && (prev === "transcribing" || prev === "stopping" || prev === "recording" || prev === "paused")) {
      root.captureDone()
    }
  }

  function open() {
    root.panelOpen = true
    root.refreshActions()
    root.refreshOffer()
  }

  function close() {
    root.panelOpen = false
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

  function runQuery(args, done) {
    if (queryProc.running) {
      queryLater.args = args
      queryLater.done = done
      queryLater.pending = true
      return
    }
    root.queryCallback = done
    root.queryOutput = ""
    root.queryArgs = args
    Qt.callLater(function() { if (!queryProc.running) queryProc.running = true })
  }

  function startRecording(name) {
    if (root.starting || root.acting) return
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
    if (root.starting || root.acting || !root.ready || !root.offerTitle) return
    var title = root.offerTitle
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

  function refreshOffer() {
    if (!root.panelOpen || !root.ready) return
    root.runQuery(["agenda"], function(code, text) {
      if (!root.ready) return
      var line = String(text || "").trim().split("\n")[0] || ""
      if (!line) {
        root.offerTitle = ""
        root.offerWhen = ""
        root.offerUrl = ""
        return
      }
      var data
      try { data = JSON.parse(line) } catch (e) {
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
    })
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
    root.runQuery(["actions"], function(code, text) {
      var lines = String(text || "").split("\n")
      var names = []
      for (var i = 0; i < lines.length; i++) {
        var name = lines[i].trim()
        if (name) names.push(name)
      }
      root.actions = names
    })
  }

  function captureDone() {
    root.captureTitle = root.title
    root.latestTries = 0
    root.pendingFolder = ""
    root.resolveLatest()
  }

  function resolveLatest() {
    root.runQuery(["latest", root.captureTitle], function(code, text) {
      var path = String(text || "").trim().split("\n")[0] || ""
      if (path) {
        root.pendingFolder = path
        root.pendingTitle = root.captureTitle || root.title
        return
      }
      root.latestTries += 1
      if (root.latestTries < 8) latestTimer.restart()
      else root.statusLine = "Couldn't find the meeting folder"
    })
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
    onTriggered: root.refreshOffer()
  }

  QtObject {
    id: queryLater
    property bool pending: false
    property var args: []
    property var done: null
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
      if (done) done(code, text)
      if (queryLater.pending) {
        var args = queryLater.args
        var next = queryLater.done
        queryLater.pending = false
        queryLater.done = null
        root.runQuery(args, next)
      }
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
          implicitHeight: Math.max(heroMark.implicitHeight, heroLabels.implicitHeight, openButton.implicitHeight)

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
            anchors.right: openButton.left
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
            id: openButton
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: "Open"
            foreground: root.foreground
            fontFamily: root.faceFont
            onClicked: root.openRecorder()
          }
        }

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
          visible: root.offerVisible

          Text {
            width: parent.width
            textFormat: Text.PlainText
            text: root.offerWhen ? root.offerWhen + "  " + root.offerTitle : root.offerTitle
            elide: Text.ElideRight
            color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.72)
            font.family: root.faceFont
            font.pixelSize: Style.font.caption
          }

          Button {
            width: parent.width
            leftAlign: true
            text: root.offerUrl ? "Join and record" : "Record this meeting"
            foreground: root.foreground
            fontFamily: root.faceFont
            enabled: !root.starting && !root.acting
            onClicked: root.joinOffer()
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
    }
  }
}
