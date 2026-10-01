import QtQuick
import qs.Commons

// Clock, meeting name, transcribing progress, and the two level tracks.
Item {
  id: root

  property color foreground: Color.foreground
  property string fontFamily: Style.font.family
  property string digits: "00:00"
  property string label: ""
  property bool showProgress: false
  property real progress: 0
  property bool metersLive: false
  property real mic: 0
  property real sys: 0

  implicitHeight: column.implicitHeight

  Column {
    id: column
    anchors.left: parent.left
    anchors.right: parent.right
    spacing: Style.space(10)

    Text {
      textFormat: Text.PlainText
      text: root.digits
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.display
      font.bold: true
    }

    Item {
      width: parent.width
      height: 3
      visible: root.showProgress

      Rectangle {
        anchors.fill: parent
        radius: 1.5
        color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.12)
      }

      Rectangle {
        width: parent.width * Math.max(0, Math.min(1, root.progress))
        height: parent.height
        radius: 1.5
        color: root.foreground
      }
    }

    Text {
      width: parent.width
      visible: root.label !== ""
      textFormat: Text.PlainText
      text: root.label
      color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.72)
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      elide: Text.ElideRight
    }

    Column {
      width: parent.width
      spacing: Style.space(8)

      Meter {
        width: parent.width
        caption: "MIC"
        level: root.metersLive ? root.mic : 0
        foreground: root.foreground
        fontFamily: root.fontFamily
      }

      Meter {
        width: parent.width
        caption: "SYS"
        level: root.metersLive ? root.sys : 0
        foreground: root.foreground
        fontFamily: root.fontFamily
      }
    }
  }

  component Meter: Item {
    id: meter

    property string caption: ""
    property real level: 0
    property color foreground: Color.foreground
    property string fontFamily: Style.font.family

    implicitHeight: label.implicitHeight

    Text {
      id: label
      width: Style.space(28)
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: meter.caption
      color: Qt.rgba(meter.foreground.r, meter.foreground.g, meter.foreground.b, 0.62)
      font.family: meter.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
      font.letterSpacing: 0.6
    }

    Item {
      id: track
      anchors.left: label.right
      anchors.leftMargin: Style.space(8)
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      height: 3

      Rectangle {
        anchors.fill: parent
        radius: 1.5
        color: Qt.rgba(meter.foreground.r, meter.foreground.g, meter.foreground.b, 0.12)
      }

      Rectangle {
        width: track.width * Math.max(0, Math.min(1, meter.level))
        height: parent.height
        radius: 1.5
        color: meter.foreground
      }
    }
  }
}
