from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFileDialog,
)
from qfluentwidgets import PushButton, BodyLabel, FluentIcon

from ui.product_ui import (
    FolderIllustration,
    apply_button_style,
    drop_zone_qss,
)


class DropZone(QFrame):
    filesDropped = Signal(list)

    def __init__(self):
        super().__init__()

        self.setAcceptDrops(True)
        self.setObjectName("dropZone")
        # H.4-P: the drop zone shares the top band with the compression panel, so
        # it is compact instead of 190 px tall. Dropping still works anywhere on
        # the frame, because the frame itself is the drop target.
        self.setMaximumHeight(300)
        self.setMinimumHeight(130)

        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mainLayout.setSpacing(7)
        self.mainLayout.setContentsMargins(16, 8, 16, 10)

        # Product-UI: an illustrated folder replaces the emoji mark. It lifts its
        # content sheet on hover and drag-over, so the drop intent is legible
        # before the user reads a single word.
        self.icon = FolderIllustration()
        self.icon.resizeTo(76)

        self.title = QLabel("Drop files or folders here")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setStyleSheet("""
            font-size:17px;
            font-weight:600;
        """)

        self.filesButton = PushButton(
            "Choose Files",
            icon=FluentIcon.FOLDER
        )
        self.filesButton.clicked.connect(self.chooseFiles)

        self.folderButton = PushButton(
            "Choose Folder",
            icon=FluentIcon.FOLDER
        )
        self.folderButton.clicked.connect(self.chooseFolder)

        buttonRow = QHBoxLayout()
        buttonRow.addStretch()
        buttonRow.setSpacing(10)
        buttonRow.addWidget(self.filesButton)
        buttonRow.addWidget(self.folderButton)
        buttonRow.addStretch()

        self.mainLayout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignHCenter)
        self.mainLayout.addWidget(self.title)
        self.mainLayout.addLayout(buttonRow)

        self._apply_theme()

    def _apply_theme(self):
        self.setStyleSheet(drop_zone_qss(self.icon.getPeek() > 0.5))
        apply_button_style(self.filesButton, "quiet")
        apply_button_style(self.folderButton, "quiet")

    def refreshTheme(self):
        """Re-apply the theme-keyed styling after a theme switch."""
        self._apply_theme()

    def resizeTo(self, width, spacing):
        """Density hook: the compact band gets a smaller folder mark."""
        self.icon.resizeTo(width)
        self.mainLayout.setSpacing(spacing)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.title.setText("Release to add files")
            self.icon.setActive(True)
            self.setStyleSheet(drop_zone_qss(True))

    def dragLeaveEvent(self, event):
        self.restoreText()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.icon.setActive(True)
        self.setStyleSheet(drop_zone_qss(True))

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self.title.text() == "Drop files or folders here":
            self.icon.setActive(False)
            self.setStyleSheet(drop_zone_qss(False))

    def dropEvent(self, event):
        self.restoreText()

        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        self.filesDropped.emit(paths)

    def chooseFiles(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Choose Files",
            "",
            "All Files (*)"
        )

        if files:
            self.filesDropped.emit(files)

    def chooseFolder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose Folder",
        )

        if folder:
            self.filesDropped.emit([folder])

    def restoreText(self):
        self.setStyleSheet(drop_zone_qss(False))
        self.icon.setActive(False)

        self.title.setText("Drop files or folders here")

    def resetPrompt(self):
        self.title.setText("Drop files or folders here")
        self.mainLayout.activate()
