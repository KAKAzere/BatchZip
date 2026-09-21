import os
import winsound
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QMessageBox,
    QScrollArea,
    QWidget,
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

    def __init__(self, success, failed, folder, failed_tasks=None):
        super().__init__()

        self.folder = folder
        failed_tasks = failed_tasks or []

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
        if failed_tasks:
            height = 390 if len(failed_tasks) == 1 else 480
            self.setFixedSize(560, height)
        else:
            self.setFixedSize(460, 260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

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
        text.setSpacing(4)

        resultLabel = StrongBodyLabel(result_text)
        resultLabel.setStyleSheet("font-size:20px;font-weight:700;")
        text.addWidget(resultLabel)

        text.addWidget(
            CaptionLabel(self._summary_text(success, failed))
        )

        top.addWidget(icon)
        top.addLayout(text)
        top.addStretch()

        layout.addLayout(top)

        if failed_tasks:
            layout.addSpacing(16)
            layout.addWidget(
                StrongBodyLabel("Failure Details")
            )

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setStyleSheet("QScrollArea { background: transparent; }")

            details = QWidget()
            details.setStyleSheet("background: transparent;")
            detailsLayout = QVBoxLayout(details)
            detailsLayout.setContentsMargins(0, 0, 0, 0)
            detailsLayout.setSpacing(0)

            for index, task in enumerate(failed_tasks):
                if index:
                    separator = QFrame()
                    separator.setFrameShape(QFrame.Shape.HLine)
                    separator.setStyleSheet(
                        "color: rgba(120, 120, 120, 45);"
                    )
                    detailsLayout.addSpacing(10)
                    detailsLayout.addWidget(separator)
                    detailsLayout.addSpacing(10)

                taskName = StrongBodyLabel(task.name)
                errorTitle, errorDetails = self._format_error_message(
                    task.error_message
                )

                detailsLayout.addWidget(taskName)
                detailsLayout.addSpacing(7)

                if errorTitle:
                    detailsLayout.addWidget(BodyLabel(errorTitle))
                    detailsLayout.addSpacing(9)

                errorMessage = CaptionLabel(errorDetails)
                errorMessage.setWordWrap(True)
                detailsLayout.addWidget(errorMessage)

            if len(failed_tasks) > 1:
                detailsLayout.addStretch()

            scroll.setWidget(details)

            if len(failed_tasks) == 1:
                scroll.setMaximumHeight(165)
                layout.addWidget(scroll)
            else:
                layout.addWidget(scroll, 1)

        outputLayout = QVBoxLayout()
        outputLayout.setSpacing(3)
        outputLayout.addWidget(CaptionLabel("Output folder"))

        folderLabel = CaptionLabel(folder)
        folderLabel.setWordWrap(True)

        outputLayout.addWidget(folderLabel)
        layout.addLayout(outputLayout)

        if len(failed_tasks) <= 1:
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

    @staticmethod
    def _summary_text(success, failed):
        if failed == 0:
            noun = "task" if success == 1 else "tasks"
            return f"{success} {noun} completed successfully."

        if success == 0:
            noun = "task" if failed == 1 else "tasks"
            return f"{failed} {noun} failed."

        completed_noun = "task" if success == 1 else "tasks"
        failed_noun = "task" if failed == 1 else "tasks"
        return (
            f"{success} {completed_noun} completed and "
            f"{failed} {failed_noun} failed."
        )

    @staticmethod
    def _format_error_message(message):
        what_marker = "\n\nWhat happened:\n"
        reasons_marker = "\n\nPossible reasons:\n"
        suggestion_marker = "\n\nSuggestion:\n"

        if not all(
            marker in message
            for marker in (what_marker, reasons_marker, suggestion_marker)
        ):
            return "", message

        title, remainder = message.split(what_marker, 1)
        what, remainder = remainder.split(reasons_marker, 1)
        reasons, suggestion = remainder.split(suggestion_marker, 1)

        if not all((title.strip(), what.strip(), reasons.strip(), suggestion.strip())):
            return "", message

        details = "\n\n".join(
            (what.strip(), reasons.strip(), suggestion.strip())
        )
        return title.strip(), details

    def openFolder(self):
        if not self.folder or not Path(self.folder).is_dir():
            QMessageBox.warning(
                self,
                "BatchZip",
                "Output Folder Unavailable\n\n"
                "What happened:\nBatchZip could not find the output folder.\n\n"
                "Possible reasons:\n- The folder may have been moved or deleted.\n\n"
                "Suggestion:\nCheck the output location, then try again."
            )
            return

        try:
            os.startfile(self.folder)
            self.accept()
        except OSError:
            QMessageBox.warning(
                self,
                "BatchZip",
                "Unable to Open Output Folder\n\n"
                "What happened:\nBatchZip could not open the output folder.\n\n"
                "Possible reasons:\n"
                "- The folder may be unavailable.\n"
                "- You may not have permission to access it.\n\n"
                "Suggestion:\nCheck the folder and its permissions, then try again."
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
