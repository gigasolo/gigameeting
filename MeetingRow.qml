import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Ui

// One meeting line. Prep is the button until a brief exists. Then Brief
// opens the note, and the caret beside that word preps again. While that
// prep runs, the same control reads Preparing. The menu floats over the rows.
Column {
  id: row

  // A Repeater fills this. The join row sets it to null.
  required property var modelData

  property color foreground: Color.foreground
  property string fontFamily: Style.font.family
  property string label: ""
  property string eventId: ""
  property string noteUrl: ""
  property bool busy: false
  property bool preparing: false
  property bool menuOpen: false

  signal openRequested()
  signal prepRequested()
  signal menuToggled()

  property bool _menuSync: false

  function applyMenu() {
    if (row._menuSync) return
    row._menuSync = true
    if (row.menuOpen) menuPopup.open()
    else menuPopup.close()
    row._menuSync = false
  }

  onMenuOpenChanged: row.applyMenu()

  readonly property bool showBrief: noteUrl.indexOf("obsidian://open?") === 0
  readonly property bool showPrep: eventId !== "" && !showBrief
  readonly property bool occupied: showBrief || showPrep

  width: parent ? parent.width : 0
  spacing: Style.space(4)

  Item {
    id: line
    width: row.width
    implicitHeight: Math.max(caption.implicitHeight, controls.implicitHeight)

    Text {
      id: caption
      anchors.left: parent.left
      anchors.right: controls.left
      anchors.rightMargin: row.occupied ? Style.space(8) : 0
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: row.label
      elide: Text.ElideRight
      color: Qt.rgba(row.foreground.r, row.foreground.g, row.foreground.b, 0.72)
      font.family: row.fontFamily
      font.pixelSize: Style.font.caption
    }

    Row {
      id: controls
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(4)

      SequentialAnimation on opacity {
        running: row.preparing
        loops: Animation.Infinite
        alwaysRunToEnd: false
        NumberAnimation { to: 0.45; duration: 650; easing.type: Easing.InOutSine }
        NumberAnimation { to: 1; duration: 650; easing.type: Easing.InOutSine }
        onRunningChanged: if (!running) controls.opacity = 1
      }

      Item {
        id: briefCluster
        visible: row.showBrief
        implicitWidth: briefRow.implicitWidth
        implicitHeight: briefRow.implicitHeight
        width: implicitWidth
        height: implicitHeight

        Row {
          id: briefRow
          spacing: 0

          Button {
            id: briefButton
            text: row.preparing ? "Preparing…" : "Brief"
            iconText: row.preparing ? "󰦖" : ""
            iconSpinning: row.preparing
            iconSize: Style.font.body
            rightPadding: row.preparing ? horizontalPadding : 0
            foreground: row.foreground
            fontFamily: row.fontFamily
            enabled: !row.preparing && !row.busy
            onClicked: row.openRequested()
          }

          Button {
            id: briefMenu
            visible: row.eventId !== "" && !row.preparing
            height: briefButton.implicitHeight
            leftPadding: 0
            rightPadding: Style.space(4)
            iconText: "󰅀"
            iconSize: Style.font.body
            iconRotation: row.menuOpen ? 180 : 0
            foreground: row.foreground
            fontFamily: row.fontFamily
            enabled: !row.preparing && !row.busy
            onClicked: row.menuToggled()
          }
        }

        Popup {
          id: menuPopup
          x: briefCluster.width - width
          y: briefCluster.height
          padding: Style.space(4)
          modal: false
          dim: false
          closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
          width: prepAgain.implicitWidth + leftPadding + rightPadding
          height: prepAgain.implicitHeight + topPadding + bottomPadding

          background: Rectangle {
            color: Color.popups.background
            border.color: Color.popups.border
            border.width: 1
            radius: Style.cornerRadius
          }

          contentItem: Button {
            id: prepAgain
            text: "Prep again"
            foreground: row.foreground
            fontFamily: row.fontFamily
            enabled: !row.preparing && !row.busy
            onClicked: row.prepRequested()
          }

          onOpenedChanged: {
            if (row._menuSync) return
            if (!opened && row.menuOpen) row.menuToggled()
          }
        }
      }

      Button {
        visible: row.showPrep
        text: row.preparing ? "Preparing…" : "Prep"
        iconText: row.preparing ? "󰦖" : ""
        iconSpinning: row.preparing
        iconSize: Style.font.body
        foreground: row.foreground
        fontFamily: row.fontFamily
        enabled: !row.preparing && !row.busy
        onClicked: row.prepRequested()
      }
    }
  }
}
