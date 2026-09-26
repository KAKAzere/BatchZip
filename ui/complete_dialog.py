import os
import re
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


class WarningArchiveDialog(QDialog):

    def __init__(self, task, parent=None):
        super().__init__(parent)

        self.task = task
        self.archive_path = task.output_path
        self.archive_action = "kept"
        self.setWindowTitle("BatchZip")
        self.setFixedSize(560, 390)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)

        title = StrongBodyLabel("Compression completed with warnings")
        title.setStyleSheet("font-size:20px;font-weight:700;")
        layout.addWidget(title)

        affected_paths, reason = self._warning_information(task.error_message)
        count = len(affected_paths)

        if count == 1:
            summary = "1 file could not be added to the archive."
        elif count > 1:
            summary = f"{count} files could not be added to the archive."
        else:
            summary = "Some files could not be added to the archive."

        message = BodyLabel(summary)
        message.setWordWrap(True)
        layout.addWidget(message)

        reason_layout = QVBoxLayout()
        reason_layout.setSpacing(3)
        reason_layout.addWidget(CaptionLabel("Reason:"))
        reason_label = BodyLabel(reason)
        reason_label.setWordWrap(True)
        reason_layout.addWidget(reason_label)
        layout.addLayout(reason_layout)

        if affected_paths:
            affected_layout = QVBoxLayout()
            affected_layout.setContentsMargins(0, 4, 0, 0)
            affected_layout.setSpacing(3)
            affected_label = (
                "Affected file:" if count == 1 else "Affected files:"
            )
            affected_layout.addWidget(CaptionLabel(affected_label))
            paths = CaptionLabel("\n".join(affected_paths))
            paths.setWordWrap(True)
            affected_layout.addWidget(paths)
            layout.addLayout(affected_layout)

        path_label = CaptionLabel(f"Archive:\n{self.archive_path}")
        path_label.setWordWrap(True)
        layout.addWidget(path_label)

        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.keepBtn = PushButton("Keep Archive")
        self.deleteBtn = PushButton("Delete Archive")
        self.keepBtn.clicked.connect(self.keepArchive)
        self.deleteBtn.clicked.connect(self.deleteArchive)
        buttons.addWidget(self.keepBtn)
        buttons.addWidget(self.deleteBtn)
        layout.addLayout(buttons)

    @staticmethod
    def _diagnostic_details(message):
        marker = "\n\n7-Zip details:\n"

        if marker in message:
            return message.split(marker, 1)[1]

        return message

    @classmethod
    def _warning_information(cls, message):
        diagnostic = cls._diagnostic_details(message)
        affected_paths = []
        seen_paths = set()

        for line in diagnostic.splitlines():
            if re.search(r"\bScan\b", line, re.IGNORECASE):
                continue

            for match in re.finditer(
                r"(?:[A-Za-z]:\\|\\\\)[^\r\n]+",
                line,
            ):
                path = re.sub(r":\s+.*$", "", match.group(0)).strip()
                key = os.path.normcase(path)

                if path and key not in seen_paths:
                    seen_paths.add(key)
                    affected_paths.append(path)

        lower_diagnostic = diagnostic.lower()
        file_in_use_markers = (
            "being used by another process",
            "used by another process",
            "sharing violation",
            "\u53e6\u4e00\u4e2a\u7a0b\u5e8f\u6b63\u5728\u4f7f\u7528\u6b64\u6587\u4ef6",
            "\u8fdb\u7a0b\u65e0\u6cd5\u8bbf\u95ee",
        )

        if any(marker in lower_diagnostic for marker in file_in_use_markers):
            reason = "The file is being used by another process."
        else:
            reason = "7-Zip could not add this file to the archive."

        return affected_paths, reason

    @classmethod
    def warning_details_text(cls, message):
        affected_paths, reason = cls._warning_information(message)
        count = len(affected_paths)

        if count == 1:
            lines = ["1 file could not be added to the archive."]
            lines.extend(("", "Affected file:", affected_paths[0]))
        elif count > 1:
            lines = [f"{count} files could not be added to the archive."]
            lines.extend(("", "Affected files:", *affected_paths))
        else:
            lines = ["Some files could not be added to the archive."]

        lines.extend(("", "Reason:", reason))
        return "\n".join(lines)

    def keepArchive(self):
        self.archive_action = "kept"
        self.accept()

    def deleteArchive(self):
        try:
            Path(self.archive_path).unlink(missing_ok=True)
        except OSError:
            self.archive_action = "delete_failed"
            self._show_delete_failure()
            self.accept()
            return

        self.archive_action = "deleted"
        self.task.output_path = ""
        self.accept()

    def _show_delete_failure(self):
        message_box = QMessageBox(self)
        message_box.setWindowTitle("BatchZip")
        message_box.setIcon(QMessageBox.Icon.Warning)
        message_box.setText(
            "Unable to delete the archive.\n\n"
            f"The file is still located at:\n{self.archive_path}"
        )
        open_button = message_box.addButton(
            "Open Folder",
            QMessageBox.ButtonRole.ActionRole,
        )
        message_box.addButton(
            "Close",
            QMessageBox.ButtonRole.RejectRole,
        )
        message_box.exec()

        if message_box.clickedButton() is open_button:
            try:
                os.startfile(str(Path(self.archive_path).parent))
            except OSError:
                QMessageBox.warning(
                    self,
                    "BatchZip",
                    "The archive folder could not be opened.",
                )


class CompleteDialog(QDialog):

    def __init__(
        self,
        success,
        warnings,
        failed,
        folder,
        warning_tasks=None,
        failed_tasks=None,
        warning_actions=None,
    ):
        super().__init__()

        self.folder = folder
        warning_tasks = warning_tasks or []
        failed_tasks = failed_tasks or []
        warning_actions = warning_actions or {}
        detail_tasks = warning_tasks + failed_tasks

        # Windows 成功提示音
        try:
            winsound.MessageBeep(
                winsound.MB_OK
                if warnings == 0 and failed == 0
                else winsound.MB_ICONEXCLAMATION
            )
        except RuntimeError:
            pass

        # Windows 系统通知
        self.showWindowsNotification(success, warnings, failed, folder)

        self.setWindowTitle("BatchZip")
        if detail_tasks:
            height = 390 if len(detail_tasks) == 1 else 480
            self.setFixedSize(560, height)
        else:
            self.setFixedSize(460, 260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        # 顶部
        top = QHBoxLayout()

        if warnings == 0 and failed == 0:
            icon_text = "✅"
            result_text = "Compression completed successfully."
        elif warnings > 0 and failed > 0:
            icon_text = "⚠️"
            result_text = "Compression completed with warnings and failures"
        elif warnings > 0:
            icon_text = "⚠️"
            result_text = "Compression completed with warnings"
        else:
            icon_text = "⚠️"
            result_text = "Compression completed with failures"

        icon = BodyLabel(icon_text)
        icon.setStyleSheet("font-size:32px;")

        text = QVBoxLayout()
        text.setSpacing(4)

        resultLabel = StrongBodyLabel(result_text)
        resultLabel.setStyleSheet("font-size:20px;font-weight:700;")
        text.addWidget(resultLabel)

        text.addWidget(
            CaptionLabel(self._summary_text(success, warnings, failed))
        )

        top.addWidget(icon)
        top.addLayout(text)
        top.addStretch()

        layout.addLayout(top)

        for task in warning_tasks:
            action = warning_actions.get(id(task))

            if not action:
                continue

            action_title, action_details = self._warning_result_message(
                task,
                action,
            )
            layout.addSpacing(8)
            layout.addWidget(StrongBodyLabel(action_title))
            action_message = BodyLabel(action_details)
            action_message.setWordWrap(True)
            layout.addWidget(action_message)

        if detail_tasks:
            layout.addSpacing(16)
            layout.addWidget(
                StrongBodyLabel("Task Details")
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

            for index, task in enumerate(detail_tasks):
                if index:
                    separator = QFrame()
                    separator.setFrameShape(QFrame.Shape.HLine)
                    separator.setStyleSheet(
                        "color: rgba(120, 120, 120, 45);"
                    )
                    detailsLayout.addSpacing(10)
                    detailsLayout.addWidget(separator)
                    detailsLayout.addSpacing(10)

                taskName = StrongBodyLabel(f"{task.name} — {task.status}")
                if task.status == "Completed with warnings":
                    errorTitle = ""
                    errorDetails = WarningArchiveDialog.warning_details_text(
                        task.error_message
                    )
                else:
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

            if len(detail_tasks) > 1:
                detailsLayout.addStretch()

            scroll.setWidget(details)

            if len(detail_tasks) == 1:
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

        if len(detail_tasks) <= 1:
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
    def _summary_text(success, warnings, failed):
        warning_noun = "warning" if warnings == 1 else "warnings"
        return (
            f"{success} completed · {warnings} {warning_noun} · "
            f"{failed} failed"
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

    @staticmethod
    def _warning_result_message(task, action):
        if action == "deleted":
            return (
                "Incomplete archive deleted",
                "The incomplete archive was deleted successfully.",
            )

        if action == "delete_failed":
            return (
                "Archive could not be deleted",
                f"The file is still available at:\n{task.output_path}",
            )

        return (
            "Archive kept with warnings",
            "The incomplete archive was kept.\n\n"
            f"Archive:\n{task.output_path}",
        )

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
    def showWindowsNotification(self, success, warnings, failed, folder):

        if Notification is None:
            return

        if warnings == 0 and failed == 0:
            title = "Compression Completed"
        elif success == 0 and warnings == 0:
            title = "Compression Failed"
        else:
            title = "Compression Completed with Warnings"

        try:
            toast = Notification(
                app_id="BatchZip",
                title=title,
                msg=(
                    f"{success} succeeded · {warnings} warnings · "
                    f"{failed} failed"
                )
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
