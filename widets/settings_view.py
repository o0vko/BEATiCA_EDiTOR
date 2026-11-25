from typing import Any

from PySide6.QtCore import QSettings, Signal
from PySide6.QtMultimedia import (
    QAudioDevice,
    QAudioOutput,
    QMediaDevices,
    QMediaPlayer,
    QPlaybackOptions,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

# 設定の永続化キー
SETTINGS_ORG = "BEATiCA"
SETTINGS_APP = "EDiTOR"


class SettingsDialog(QDialog):
    """音声出力（スピーカー）と低遅延モードを設定するダイアログ"""

    autosaveIntervalChanged = Signal(int)
    iconSizeChanged = Signal(str)

    def __init__(self, player: QMediaPlayer, audioOutput: QAudioOutput, parent=None):
        super().__init__(parent)
        self.player = player
        self.audioOutput = audioOutput

        self.setWindowTitle("設定")
        self.setModal(True)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # 出力デバイス（スピーカー）
        self.deviceCombo = QComboBox()
        self.devices: list[QAudioDevice] = list(QMediaDevices.audioOutputs())
        if not self.devices:
            self.deviceCombo.addItem("利用可能な出力デバイスがありません")
            self.deviceCombo.setEnabled(False)
        else:
            for device in self.devices:
                self.deviceCombo.addItem(device.description(), device)
            self._selectCurrentDevice()
        form.addRow(QLabel("出力デバイス (スピーカー)"), self.deviceCombo)

        # 再生モード（低遅延）
        self.intentCombo = QComboBox()
        self.intentCombo.addItem("標準", QPlaybackOptions.PlaybackIntent.Playback)
        self.intentCombo.addItem(
            "低遅延 (LowLatencyStreaming)",
            QPlaybackOptions.PlaybackIntent.LowLatencyStreaming,
        )
        self._selectCurrentIntent()
        form.addRow(QLabel("再生モード"), self.intentCombo)

        # オートセーブ間隔（秒、0で無効）
        self.autosaveSpin = QSpinBox()
        self.autosaveSpin.setRange(0, 3600)
        self.autosaveSpin.setValue(
            int(
                str(
                    QSettings(SETTINGS_ORG, SETTINGS_APP).value(
                        "autosave/intervalSec", 60
                    )
                )
            )
        )
        self.autosaveSpin.valueChanged.connect(self.onAutosaveIntervalChanged)
        form.addRow(QLabel("オートセーブ間隔 (秒, 0=無効)"), self.autosaveSpin)

        # アイコンサイズ（小/中/大）
        self.iconSizeCombo = QComboBox()
        self.iconSizeCombo.addItem("小", "small")
        self.iconSizeCombo.addItem("中 (PC版デフォルト)", "medium")
        self.iconSizeCombo.addItem("大 (スマホ版デフォルト)", "large")
        currentIconSize = str(
            QSettings(SETTINGS_ORG, SETTINGS_APP).value("ui/iconSize", "medium")
        )
        idx = self.iconSizeCombo.findData(currentIconSize)
        if idx >= 0:
            self.iconSizeCombo.setCurrentIndex(idx)
        self.iconSizeCombo.activated.connect(self.onIconSizeChanged)
        form.addRow(QLabel("アイコンサイズ"), self.iconSizeCombo)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _currentDevice(self) -> QAudioDevice:
        return self.audioOutput.device()

    def onAutosaveIntervalChanged(self, value: int):
        QSettings(SETTINGS_ORG, SETTINGS_APP).setValue("autosave/intervalSec", value)
        self.autosaveIntervalChanged.emit(value)

    def onIconSizeChanged(self, index: int):
        key = self.iconSizeCombo.itemData(index)
        QSettings(SETTINGS_ORG, SETTINGS_APP).setValue("ui/iconSize", key)
        self.iconSizeChanged.emit(key)

    def _selectCurrentDevice(self):
        current = self._currentDevice()
        index = next(
            (i for i, d in enumerate(self.devices) if d.id() == current.id()),
            0,
        )
        self.deviceCombo.setCurrentIndex(index)

    def _selectCurrentIntent(self):
        options = self.player.playbackOptions()
        intent = options.playbackIntent()
        index = self.intentCombo.findData(intent)
        if index >= 0:
            self.intentCombo.setCurrentIndex(index)

    def apply(self):
        """選択内容を実際の出力へ適用して保存"""
        if self.devices:
            device = self.deviceCombo.currentData()
            if isinstance(device, QAudioDevice):
                self.audioOutput.setDevice(device)

        intent = self.intentCombo.currentData()
        options = QPlaybackOptions()
        if intent is not None:
            options.setPlaybackIntent(intent)
        self.player.setPlaybackOptions(options)

        self.save()

    def save(self):
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        if self.devices:
            settings.setValue(
                "audio/deviceId", bytes(self.deviceCombo.currentData().id())
            )
        intent = self.intentCombo.currentData()
        if intent is not None:
            settings.setValue("audio/playbackIntent", int(intent.value))

    def accept(self):
        self.apply()
        super().accept()


def applySavedAudioSettings(player: QMediaPlayer, audioOutput: QAudioOutput):
    """保存済みの音声設定を読み込んで適用する（起動時に呼ぶ）"""
    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)

    # 低遅延モード
    intentValue = settings.value("audio/playbackIntent", None)
    if intentValue is not None:
        try:
            intent = QPlaybackOptions.PlaybackIntent(int(str(intentValue)))
        except ValueError:
            intent = QPlaybackOptions.PlaybackIntent.Playback
        options = QPlaybackOptions()
        options.setPlaybackIntent(intent)
        player.setPlaybackOptions(options)

    # 出力デバイス
    deviceId = settings.value("audio/deviceId", None)
    if deviceId is not None:
        deviceIdAny: Any = deviceId
        if isinstance(deviceIdAny, str):
            deviceIdBytes = deviceIdAny.encode("latin-1", errors="ignore")
        elif isinstance(deviceIdAny, (bytes, bytearray)):
            deviceIdBytes = bytes(deviceIdAny)
        else:
            dataAttr = getattr(deviceIdAny, "data", None)
            deviceIdBytes = bytes(dataAttr()) if callable(dataAttr) else b""
        target = next(
            (
                d
                for d in QMediaDevices.audioOutputs()
                if bytes(d.id().data()) == deviceIdBytes
            ),
            None,
        )
        if target is not None:
            audioOutput.setDevice(target)
