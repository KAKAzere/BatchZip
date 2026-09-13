import os
import winsound
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QMessageBox
)

from qfluentwidgets import (
    StrongBodyLabel,
    BodyLabel,
    CaptionLabel,
    PushButton
)

try:
    from winotify import Notification, audio
except ImportError:
    Notification = None
    audio = None


class CompleteDialog(QDialog):

    def __init__(self, success, failed, folder):
        super().__init__()

        self.folder = folder

        # Windows 成功提示音
        try:
            winsound.MessageBeep(
                winsound.MB_OK if failed == 0 else winsound.MB_ICONEXCLAMATION
            )
        except RuntimeError:
            pass

        # Windows 系统通知
        self.showWindowsNotification(success, failed, folder)

        self.setWindowTitle("BatchZip")
        self.setFixedSize(460, 300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        # 顶部
        top = QHBoxLayout()

        if failed == 0:
            icon_text = "✅"
            result_text = "Compression completed successfully."
        elif success == 0:
            icon_text = "❌"
            result_text = "Compression failed."
        else:
            icon_text = "⚠️"
            result_text = "Compression completed with some failures."

        icon = BodyLabel(icon_text)
        icon.setStyleSheet("font-size:32px;")

        text = QVBoxLayout()

        text.addWidget(
            StrongBodyLabel(result_text)
        )

        text.addWidget(
            CaptionLabel("BatchZip")
        )

        top.addWidget(icon)
        top.addLayout(text)
        top.addStretch()

        layout.addLayout(top)

        # 统计卡片
        card = QFrame()
        card.setStyleSheet("""
        QFrame{
            border:1px solid rgba(120,120,120,60);
            border-radius:12px;
            background:rgba(255,255,255,15);
        }
        """)

        cardLayout = QVBoxLayout(card)
        cardLayout.setContentsMargins(16,16,16,16)

        cardLayout.addWidget(
            BodyLabel(f"Success: {success}")
        )

        cardLayout.addWidget(
            BodyLabel(f"Failed: {failed}")
        )

        layout.addWidget(card)

        layout.addWidget(
            StrongBodyLabel("Output Folder")
        )

        folderLabel = CaptionLabel(folder)
        folderLabel.setWordWrap(True)

        layout.addWidget(folderLabel)

        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()

        closeBtn = PushButton("Close")
        openBtn = PushButton("Open Folder")

        closeBtn.clicked.connect(self.reject)
        openBtn.clicked.connect(self.openFolder)

        buttons.addWidget(closeBtn)
        buttons.addWidget(openBtn)

        layout.addLayout(buttons)

    def openFolder(self):
        if not self.folder or not Path(self.folder).is_dir():
            QMessageBox.warning(
                self,
                "BatchZip",
                "The output folder is no longer available."
            )
            return

        try:
            os.startfile(self.folder)
            self.accept()
        except OSError as exc:
            QMessageBox.warning(
                self,
                "BatchZip",
                f"Unable to open the output folder:\n{exc}"
            )

    # -----------------------------
    # Windows 原生通知
    # -----------------------------
    def showWindowsNotification(self, success, failed, folder):

        if Notification is None:
            return

        if failed == 0:
            title = "Compression Completed"
        elif success == 0:
            title = "Compression Failed"
        else:
            title = "Compression Completed with Warnings"

        try:
            toast = Notification(
                app_id="BatchZip",
                title=title,
                msg=f"{success} succeeded · {failed} failed"
            )

            toast.set_audio(audio.Default, loop=False)

            if folder and Path(folder).is_dir():
                toast.add_actions(
                    label="Open Folder",
                    launch=Path(folder).resolve().as_uri()
                )

            toast.show()
        except Exception:
            # A notification failure must never hide the completion dialog.
            pass
