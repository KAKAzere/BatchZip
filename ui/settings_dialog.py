"""The Settings panel behind the header gear.

It is deliberately not a navigation frame: BatchZip has one setting, so this is
a single compact card with one group and one row. When a second page of settings
actually exists, the surrounding frame can be introduced then.

The dialog owns no theme state. It reports the chosen mode and the window
applies it, so there is still exactly one place that changes the theme.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout

from qfluentwidgets import (BodyLabel, CaptionLabel, FluentStyleSheet,
                            SegmentedWidget, StrongBodyLabel, isDarkTheme, qconfig)

from ui.native_title_bar import apply_title_bar_theme

# The stored tokens double as the segmented route keys.
MODES = (("system", "System"), ("light", "Light"), ("dark", "Dark"))
_TOKEN_FOR_MODE = {"system": "system", "light": "light", "dark": "dark"}


class SettingsDialog(QDialog):
    """Appearance settings. Emits the chosen route token, nothing else."""

    themeModeChosen = Signal(str)

    def __init__(self, token, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Settings")
        self.setModal(False)
        self.setFixedWidth(400)
        # A bare QDialog keeps the light application palette, so it has to ask
        # qfluentwidgets for its own sheet or it stands out in dark theme.
        FluentStyleSheet.DIALOG.apply(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(4)

        heading = StrongBodyLabel("Settings")
        layout.addWidget(heading)
        layout.addSpacing(18)

        self.appearanceHeader = CaptionLabel("Appearance")
        layout.addWidget(self.appearanceHeader)
        layout.addSpacing(10)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.themeLabel = BodyLabel("Theme")
        row.addWidget(self.themeLabel)
        row.addStretch(1)

        self.selector = SegmentedWidget()
        self.selector.setFixedWidth(210)
        for route, text in MODES:
            # The item emits its click as a bool (PivotItem.itemClicked), so the
            # handler has to absorb that argument; otherwise it replaces the
            # captured route and every click would report the wrong mode.
            self.selector.addItem(
                route, text, onClick=lambda *_, key=route: self._onChosen(key))
        row.addWidget(self.selector)

        layout.addLayout(row)
        layout.addStretch(1)

        self.selector.setCurrentItem(token if token in _TOKEN_FOR_MODE else "system")
        self._token = self.selector.currentRouteKey()

    # ------------------------------------------------------------------ events

    def _onChosen(self, key):
        """Report a user click. Selection state is already drawn by the widget."""
        if key == self._token:
            return
        self._token = key
        self.themeModeChosen.emit(key)

    def showEvent(self, event):
        """Tint the caption on every show.

        The dialog keeps its native handle between openings, but the theme can
        have changed while it was hidden, so it is re-applied rather than assumed.
        """
        super().showEvent(event)
        apply_title_bar_theme(self, isDarkTheme())
        qconfig.themeChanged.connect(self._onThemeChanged)

    def _onThemeChanged(self, *_):
        apply_title_bar_theme(self, isDarkTheme())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
