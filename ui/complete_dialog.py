import os
import re
import winsound
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QMessageBox,
    QScrollArea,
    QWidget,
)

from ui.product_ui import apply_button_style, danger_color

from qfluentwidgets import (
    StrongBodyLabel,
    BodyLabel,
    CaptionLabel,
    PushButton,
    ToolButton,
    FluentIcon,
    FluentStyleSheet,
    isDarkTheme,
)

try:
    from winotify import Notification, audio
except ImportError:
    Notification = None
    audio = None


# --------------------------------------------------------------------------
# H.5-P failure presentation
#
# The dialog below shows the user four things and nothing else: which file,
# where it is, what happened, and why. The raw 7-Zip diagnostic is still stored
# on the task - it is simply not part of the default UI any more.
# --------------------------------------------------------------------------

# Only markers that literally appear in the stored message are used. A return
# code alone is never turned into a guess: code 2 can mean many different
# things, so it stays a generic "Compression failed".
_ACCESS_DENIED_MARKERS = (
    "access is denied", "access denied", "permission denied",
    "\u62d2\u7edd\u8bbf\u95ee", "\u6743\u9650",
    "being used by another process", "sharing violation",
    "\u53e6\u4e00\u4e2a\u7a0b\u5e8f\u6b63\u5728\u4f7f\u7528", "\u8fdb\u7a0b\u65e0\u6cd5\u8bbf\u95ee",
)
_NOT_FOUND_MARKERS = (
    "cannot find the file", "cannot find the path", "file not found",
    "no such file", "does not exist",
    "\u627e\u4e0d\u5230", "\u7cfb\u7edf\u627e\u4e0d\u5230\u6307\u5b9a\u7684\u6587\u4ef6",
)
_OUTPUT_MARKERS = (
    "not enough space", "disk full", "cannot create the file",
    "error writing", "cannot write",
    "\u78c1\u76d8\u7a7a\u95f4\u4e0d\u8db3", "\u65e0\u6cd5\u521b\u5efa",
)

# BatchZip's own specific failure titles. The generic "Compression Failed"
# title is deliberately absent: it carries no root-cause information.
_TITLE_REASONS = {
    "7-zip not found": ("7-Zip not available",
                        "BatchZip could not find 7-Zip on this PC."),
    "unable to start 7-zip": ("7-Zip could not start",
                              "The 7-Zip program could not be launched."),
    "compression cancelled": ("Compression cancelled",
                              "The task was cancelled before it finished."),
}

# The classifier result BatchZip already stored, which is evidence rather than
# a guess. Return code 1 is a warning, so it is not listed here.
_RESULT_REASONS = {
    "interrupted": ("Compression interrupted",
                    "7-Zip stopped before the archive was completed."),
    "not enough memory": ("Not enough memory",
                          "There was not enough memory to finish the archive."),
    "command line error": ("Compression command rejected",
                           "7-Zip rejected the compression command."),
    "fatal error": ("Compression failed",
                    "7-Zip could not complete the archive."),
    "unknown error": ("Unknown compression error",
                      "The archive result could not be determined."),
}

DEFAULT_REASON = ("Unknown compression error",
                  "The archive result could not be determined.")

# Failure keeps a semantic red rather than the brand accent. The colour now
# comes from the shared product visual language so the dialogs and the main
# window cannot drift apart.

def failure_display_reason(task):
    """User-facing reason for one failed task.

    Strictly evidence based, in order of specificity:
      1. a specific BatchZip failure title,
      2. a marker that literally appears in the stored message,
      3. the classifier result BatchZip already recorded,
      4. a neutral fallback.
    Nothing is inferred from a return code on its own.
    """
    message = task.error_message or ""
    lowered = message.lower()

    head = message.split("\n", 1)[0].strip().lower()
    if head in _TITLE_REASONS:
        return _TITLE_REASONS[head]

    for title, description, markers in (
        ("Access denied", "The file could not be accessed.", _ACCESS_DENIED_MARKERS),
        ("Source file not found", "The source file no longer exists.", _NOT_FOUND_MARKERS),
        ("Output location unavailable", "The output location could not be used.",
         _OUTPUT_MARKERS),
    ):
        if any(marker in lowered for marker in markers):
            return title, description

    match = re.search(r"Return Code\s+\d+:\s*([^\n]+)", message)
    if match:
        result = match.group(1).strip().lower()
        if result in _RESULT_REASONS:
            return _RESULT_REASONS[result]
    return DEFAULT_REASON


def failure_detail(task):
    """The task's own one-line explanation, when it has one.

    A stored failure message carries a plain-English "What happened:" sentence.
    Using it keeps the reason specific to the actual failure rather than a canned
    string, while still hiding the return code, the internal classifier wording
    and the raw 7-Zip output that this presentation removes.
    """
    match = re.search(r"What happened:\s*\n\s*(.+)", task.error_message or "")
    if match:
        detail = match.group(1).strip()
        if detail:
            return detail
    return failure_display_reason(task)[1]


def failure_groups(failed_tasks):
    """Group failed tasks by user-facing reason.

    Groups are ordered by size, largest first, and ties keep first-seen order so
    the list never reshuffles between runs. Members keep the original task order.
    """
    groups = {}
    order = []
    for task in failed_tasks:
        title, description = failure_display_reason(task)
        if title not in groups:
            groups[title] = {"title": title, "description": description, "tasks": []}
            order.append(title)
        groups[title]["tasks"].append(task)
    ranked = sorted(order, key=lambda name: (-len(groups[name]["tasks"]), order.index(name)))
    return [groups[name] for name in ranked]


def reveal_location(path):
    """Open the folder that contains `path`. Returns True when it opened."""
    if not path:
        return False
    folder = Path(path).parent
    if not folder.is_dir():
        return False
    try:
        os.startfile(str(folder))
        return True
    except OSError:
        return False


def elide_middle(label, full_text):
    """Middle-elide `full_text` into `label` for the width it currently has.

    The caller keeps the original string and calls this again on resize, so a
    widened window re-elides instead of keeping the first result.
    """
    metrics = QFontMetrics(label.font())
    elided = metrics.elidedText(full_text, Qt.TextElideMode.ElideMiddle,
                                max(0, label.width() - 2))
    if elided != label.text():
        label.setText(elided)


class _FailureRow(QWidget):
    """One compact failure row: name, path, open-location."""

    ROW_HEIGHT = 38

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.ROW_HEIGHT)
        path = task.path or ""
        self._path = path
        self._pathText = path or "Path unavailable"
        self._name = task.name or (Path(path).name if path else "") or "Unnamed task"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 4, 0)
        layout.setSpacing(12)

        self.nameLabel = CaptionLabel(self._name)
        self.nameLabel.setMinimumWidth(150)
        self.nameLabel.setMaximumWidth(260)
        self.nameLabel.setStyleSheet("font-weight:600;")
        self.nameLabel.setToolTip(self._name)

        self.pathLabel = CaptionLabel(self._pathText)
        self.pathLabel.setMinimumWidth(60)
        if path:
            self.pathLabel.setToolTip(path)

        self.openButton = ToolButton(FluentIcon.FOLDER, self)
        self.openButton.setFixedSize(28, 28)
        available = bool(path) and Path(path).parent.is_dir()
        self.openButton.setEnabled(available)
        self.openButton.setToolTip("Open file location" if available
                                   else "Location unavailable")
        if available:
            self.openButton.clicked.connect(self._openLocation)

        layout.addWidget(self.nameLabel, 0)
        layout.addWidget(self.pathLabel, 1)
        layout.addWidget(self.openButton, 0)

    def _openLocation(self):
        reveal_location(self._path)

    def _elide(self):
        elide_middle(self.nameLabel, self._name)
        elide_middle(self.pathLabel, self._pathText)

    def showEvent(self, event):
        super().showEvent(event)
        self._elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def paintEvent(self, event):
        """Very light row separator, no card chrome."""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QPen(QColor(255, 255, 255, 18) if isDarkTheme()
                            else QColor(0, 0, 0, 16), 1))
        painter.drawLine(10, self.height() - 1, self.width() - 10, self.height() - 1)
        painter.end()


class _FailureGroup(QWidget):
    """Group header (reason + count) followed by its compact rows."""

    def __init__(self, group, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(10, 14, 10, 2)
        header.setSpacing(8)
        title = StrongBodyLabel(group["title"])
        count = CaptionLabel("%d file%s" % (len(group["tasks"]),
                                            "" if len(group["tasks"]) == 1 else "s"))
        header.addWidget(title)
        header.addWidget(count)
        header.addStretch()
        layout.addLayout(header)

        if group["description"]:
            caption = CaptionLabel(group["description"])
            caption.setContentsMargins(10, 0, 10, 6)
            layout.addWidget(caption)

        for task in group["tasks"]:
            layout.addWidget(_FailureRow(task, self))


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
        if failed_tasks:
            self._buildFailurePresentation(success, warnings, failed, folder,
                                           warning_tasks, failed_tasks, warning_actions)
        else:
            self._buildDefaultPresentation(success, warnings, failed, folder,
                                           warning_tasks, failed_tasks, warning_actions)

    def _buildDefaultPresentation(self, success, warnings, failed, folder,
                                  warning_tasks, failed_tasks, warning_actions):
        """Success and warning result, unchanged."""
        detail_tasks = warning_tasks + failed_tasks

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

        # Same feedback language as the main window's action buttons.
        apply_button_style(openBtn, "quiet")
        apply_button_style(closeBtn, "quiet")

        closeBtn.clicked.connect(self.reject)
        openBtn.clicked.connect(self.openFolder)

        buttons.addWidget(closeBtn)
        buttons.addWidget(openBtn)

        layout.addLayout(buttons)

    # ======================================================================
    # H.5-P failure result
    # ======================================================================

    def _buildFailurePresentation(self, success, warnings, failed, folder,
                                  warning_tasks, failed_tasks, warning_actions):
        """Failure result: which file, where it is, what happened, and why.

        The raw 7-Zip diagnostic, the return code and the internal classifier
        wording all stay on the task - they are deliberately absent here.
        """
        groups = failure_groups(failed_tasks)
        single = len(failed_tasks) == 1

        # A bare QDialog keeps the light palette in dark theme, which leaves the
        # Fluent labels unreadable on it. Only dark mode is overridden here so
        # the light appearance stays as it was.
        if isDarkTheme():
            FluentStyleSheet.DIALOG.apply(self)

        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        width = 600 if single else 780
        max_height = 720
        if available is not None:
            width = min(width, int(available.width() * 0.7))
            max_height = int(available.height() * 0.75)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(8)
        mark = CaptionLabel("\u26a0")
        mark.setStyleSheet("color:%s;font-size:15px;font-weight:700;" % danger_color())
        # The result-mix wording is the existing RC5 contract: the completion
        # tests lock in both this title and the summary line for each
        # success / warning / failure split, so the failure redesign keeps the
        # same wording and changes only the body below it.
        if warnings > 0:
            title_text = "Compression completed with warnings and failures"
        else:
            title_text = "Compression completed with failures"
        title = StrongBodyLabel(title_text)
        title.setStyleSheet("font-size:17px;font-weight:700;")
        header.addWidget(mark)
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        caption = CaptionLabel(self._summary_text(success, warnings, failed))
        caption.setContentsMargins(23, 0, 0, 0)
        layout.addWidget(caption)

        layout.addSpacing(10)

        if single:
            self._buildSingleFailure(layout, failed_tasks[0])
        else:
            self._buildFailureGroups(layout, groups, max_height)

        # Warnings keep their existing presentation instead of being pulled into
        # this redesign: the same title + details pair the default path renders.
        for task in warning_tasks:
            action_title, action_details = self._warning_result_message(
                task,
                warning_actions.get(id(task), "kept"),
            )
            layout.addSpacing(8)
            layout.addWidget(StrongBodyLabel(action_title))
            action_message = BodyLabel(action_details)
            action_message.setWordWrap(True)
            layout.addWidget(action_message)

        layout.addSpacing(6)
        buttons = QHBoxLayout()
        buttons.addStretch()
        if single:
            path = failed_tasks[0].path or ""
            open_button = ToolButton(FluentIcon.FOLDER, self)
            open_button.setFixedSize(30, 30)
            usable = bool(path) and Path(path).parent.is_dir()
            open_button.setEnabled(usable)
            open_button.setToolTip("Open file location" if usable else "Location unavailable")
            if usable:
                open_button.clicked.connect(lambda: reveal_location(path))
            buttons.addWidget(open_button)
            buttons.addSpacing(6)
        close_button = PushButton("Close")
        apply_button_style(close_button, "quiet")
        close_button.clicked.connect(self.reject)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        layout.activate()
        if single:
            # Height fits the content so no scrollbar appears, but the width
            # stays adjustable - a wider dialog must re-elide the path.
            self.setMinimumWidth(460)
            self.resize(width, self.sizeHint().height())
            self.setFixedHeight(self.sizeHint().height())
        else:
            # Grow with the content up to the screen cap, instead of always
            # taking the full height and leaving a large empty area. A scroll
            # area reports its own capped hint, so the real content height is
            # used in its place.
            self._failureBody.adjustSize()
            content = self._failureBody.sizeHint().height()
            wanted = (self.sizeHint().height() - self._failureScroll.sizeHint().height()
                      + content)
            self.setMinimumWidth(560)
            self.setMinimumHeight(260)
            self.setMaximumHeight(max_height)
            self.resize(width, max(260, min(max_height, wanted)))

    def _buildSingleFailure(self, layout, task):
        """One failed task, with no repetition of the page-level status."""
        path = task.path or ""
        name = task.name or (Path(path).name if path else "Unnamed task")

        card = QFrame()
        card.setObjectName("failureCard")
        card.setStyleSheet(
            "#failureCard { border: 1px solid rgba(120,120,120,60); border-radius: 10px; }"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(6)

        name_row = QHBoxLayout()
        name_row.setSpacing(10)
        name_label = CaptionLabel(name)
        name_label.setStyleSheet("font-size:14px;font-weight:600;")
        name_label.setToolTip(name)
        self._singleName = name_label
        self._singleNameText = name
        badge = CaptionLabel("Failed")
        badge.setStyleSheet(
            "color:%s;background:rgba(192,57,43,40);"
            "border:1px solid rgba(192,57,43,90);border-radius:9px;padding:0 8px;"
            % danger_color()
        )
        badge.setFixedHeight(18)
        name_row.addWidget(name_label, 1)
        name_row.addWidget(badge, 0)
        card_layout.addLayout(name_row)

        path_label = CaptionLabel(path or "Path unavailable")
        if path:
            path_label.setToolTip(path)
        self._singlePath = path_label
        self._singlePathText = path or "Path unavailable"
        card_layout.addWidget(path_label)

        reason = BodyLabel(failure_detail(task))
        reason.setWordWrap(True)
        reason.setContentsMargins(0, 6, 0, 0)
        card_layout.addWidget(reason)

        layout.addWidget(card)

    def _buildFailureGroups(self, layout, groups, max_height):
        """Reason groups first, then the files inside them."""
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        for group in groups:
            body_layout.addWidget(_FailureGroup(group, body))
        body_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        # The viewport is a plain child widget and would otherwise fill with the
        # palette base colour, which stays light in dark theme. The area, its
        # viewport and the scrolled widget are all made transparent so the dialog
        # surface shows through in both themes.
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
            "QScrollArea > QWidget { background: transparent; }"
        )
        scroll.viewport().setAutoFillBackground(False)
        body.setAutoFillBackground(False)
        layout.addWidget(scroll)
        self._failureBody = body
        self._failureScroll = scroll

    def _elidePaths(self):
        """Re-elide whatever this dialog is currently showing."""
        if hasattr(self, "_singlePath"):
            elide_middle(self._singlePath, self._singlePathText)
            elide_middle(self._singleName, self._singleNameText)

    def showEvent(self, event):
        super().showEvent(event)
        self._elidePaths()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elidePaths()

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
