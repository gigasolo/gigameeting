import QtQuick

// Ring and disc for the bar slot. Drawn in QML so it stays sharp at 16px
// and takes the bar color, the same approach as the Tailscale grid.
Item {
  id: root

  property real iconSize: 16
  property color color: "white"
  property color discColor: "#e5484d"
  property bool discFilled: false
  property bool pulsing: false

  implicitWidth: iconSize
  implicitHeight: iconSize
  width: iconSize
  height: iconSize

  Rectangle {
    anchors.centerIn: parent
    width: root.iconSize * 0.78
    height: width
    radius: width / 2
    color: "transparent"
    border.width: Math.max(1.5, root.iconSize * 0.1)
    border.color: root.color
  }

  Rectangle {
    anchors.centerIn: parent
    width: root.iconSize * 0.36
    height: width
    radius: width / 2
    visible: root.discFilled
    color: root.discColor

    SequentialAnimation on opacity {
      running: root.pulsing && root.discFilled
      loops: Animation.Infinite
      alwaysRunToEnd: true
      NumberAnimation { to: 0.35; duration: 700; easing.type: Easing.InOutSine }
      NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine }
      onRunningChanged: if (!running) parent.opacity = 1
    }
  }
}
