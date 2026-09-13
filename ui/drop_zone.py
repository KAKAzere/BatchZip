from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFileDialog,
)
from qfluentwidgets import PushButton, BodyLabel, FluentIcon


class DropZone(QFrame):
    filesDropped = Signal(list)

    def __init__(self):
        super().__init__()

        self.setAcceptDrops(True)
        self.setObjectName("dropZone")
        self.setMaximumHeight(300)
        self.setMinimumHeight(140)

        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mainLayout.setSpacing(6)
        self.mainLayout.setContentsMargins(16, 10, 16, 10)

        self.icon = QLabel("📦")
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon.setStyleSheet("font-size:56px;")

        self.title = QLabel("Drag files or folders here")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setStyleSheet("""
            font-size:22px;
            font-weight:600;
        """)

        self.hint = BodyLabel("Supports multiple files and folders")

        self.countLabel = BodyLabel("0 files in queue")
        self.countLabel.hide()

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
        buttonRow.setSpacing(10)
        buttonRow.addWidget(self.filesButton)
        buttonRow.addWidget(self.folderButton)

        self.mainLayout.addWidget(self.icon)
        self.mainLayout.addWidget(self.title)
        self.mainLayout.addWidget(self.hint)
        self.mainLayout.addWidget(self.countLabel)
        self.mainLayout.addLayout(buttonRow)

        self.normalStyle = """
        #dropZone{
            border:2px dashed rgba(120,120,120,140);
            border-radius:18px;
            background:rgba(255,255,255,18);
        }
        """

        self.hoverStyle = """
        #dropZone{
            border:2px dashed #2563EB;
            border-radius:18px;
            background:rgba(37,99,235,35);
        }
        """

        self.setStyleSheet(self.normalStyle)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.title.setText("Release to add files")
            self.setStyleSheet(self.hoverStyle)

    def dragLeaveEvent(self, event):
        self.restoreText()

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
        self.setStyleSheet(self.normalStyle)

        if self.countLabel.isHidden():
            self.title.setText("Drag files or folders here")
        else:
            self.title.setText("BatchZip Queue")

    def updateQueueCount(self, count):
        if count == 0:
            self.title.setText("Drag files or folders here")

            self.hint.show()
            self.countLabel.hide()

            self.icon.setStyleSheet("font-size:56px;")
            self.title.setStyleSheet("""
                font-size:22px;
                font-weight:600;
            """)

        else:
            word = "file" if count == 1 else "files"

            self.title.setText("BatchZip Queue")
            self.countLabel.setText(f"{count} {word} in queue")

            self.hint.hide()
            self.countLabel.show()

            self.icon.setStyleSheet("font-size:22px;")
            self.title.setStyleSheet("""
                font-size:16px;
                font-weight:600;
            """)

        self.mainLayout.activate()
