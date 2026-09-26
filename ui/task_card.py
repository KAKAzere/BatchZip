from PySide6.QtCore import (
    Qt,
    Signal,
    QPoint,
    QPropertyAnimation,
    QEasingCurve,
)
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QSizePolicy,
    QGraphicsOpacityEffect,
)

from qfluentwidgets import (
    StrongBodyLabel,
    CaptionLabel,
    ProgressBar,
    FluentIcon,
    ToolButton,
)

from core.task import Task


class TaskCard(QFrame):

    # 动画结束后真正通知 MainWindow 删除
    removeFinished = Signal(object)

    STATUS_COLORS = {
        "Waiting": "#909399",
        "Compressing": "#2563EB",
        "Completed": "#16A34A",
        "Completed with warnings": "#D97706",
        "Failed": "#DC2626",
        "Cancelled": "#D97706",
    }

    STATUS_ICON = {
        "Waiting": "○",
        "Compressing": "◐",
        "Completed": "✓",
        "Completed with warnings": "⚠",
        "Failed": "✕",
        "Cancelled": "■",
    }

    def __init__(self, task: Task):
        super().__init__()

        self.task = task
        self.queueLocked = False

        self.normalHeight = 92
        self.compactHeight = 74

        self.setObjectName("taskCard")

        # 注意：不要用 self.layout，那会覆盖 QWidget.layout()
        self.mainLayout = QHBoxLayout(self)
        self.mainLayout.setContentsMargins(18, 14, 18, 14)
        self.mainLayout.setSpacing(14)

        # ---------------- 左侧：Grip + 文件图标 ----------------
        left = QHBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(8)

        self.grip = CaptionLabel("⋮⋮")
        self.grip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.grip.setStyleSheet(
            "color:#909399;font-size:16px;"
            "font-weight:bold;background:transparent;"
        )
        self.grip.setToolTip("Drag to reorder")

        self.icon = CaptionLabel("📁" if task.is_folder else "📄")
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        left.addWidget(self.grip)
        left.addWidget(self.icon)

        # ---------------- 中间列：文件名 + 状态 / 大小 / 进度 ----------------
        center = QFrame()
        center.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        self.infoLayout = QVBoxLayout(center)
        self.infoLayout.setContentsMargins(0, 0, 0, 0)
        self.infoLayout.setSpacing(4)

        self.nameLabel = StrongBodyLabel(task.name)
        self.sizeLabel = CaptionLabel(task.size)

        # 状态标签（固定占位，不会被挤掉）
        self.statusLabel = CaptionLabel()
        self.statusLabel.setAlignment(
            Qt.AlignmentFlag.AlignRight |
            Qt.AlignmentFlag.AlignVCenter
        )

        # 淡入动画（状态切换用）
        self.opacity = QGraphicsOpacityEffect(self.statusLabel)
        self.statusLabel.setGraphicsEffect(self.opacity)

        self.fade = QPropertyAnimation(self.opacity, b"opacity", self)
        self.fade.setDuration(180)

        # 名称行：文件名 ←→ 状态
        nameRow = QHBoxLayout()
        nameRow.setContentsMargins(0, 0, 0, 0)
        nameRow.setSpacing(8)
        nameRow.addWidget(self.nameLabel)
        nameRow.addStretch()
        nameRow.addWidget(self.statusLabel)

        self.progress = ProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(task.progress)

        self.infoLayout.addLayout(nameRow)
        self.infoLayout.addWidget(self.sizeLabel)
        self.infoLayout.addWidget(self.progress)

        # ---------------- 右列：垃圾桶（常驻） ----------------
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.setAlignment(
            Qt.AlignmentFlag.AlignRight |
            Qt.AlignmentFlag.AlignVCenter
        )

        self.removeBtn = ToolButton()
        self.removeBtn.setIcon(FluentIcon.DELETE)
        self.removeBtn.setFixedSize(32, 32)
        self.removeBtn.setCursor(Qt.CursorShape.PointingHandCursor)

        self.removeBtn.clicked.connect(self.startRemoveAnimation)

        right.addWidget(self.removeBtn, 0, Qt.AlignmentFlag.AlignRight)

        self.mainLayout.addLayout(left)
        self.mainLayout.addWidget(center)
        self.mainLayout.addLayout(right)

        self.setStyleSheet("""
        #taskCard{
            border:1px solid rgba(120,120,120,60);
            border-radius:16px;
            background:rgba(255,255,255,20);
        }
        """)

        self.setCompact(task.compact)
        self.updateStatus(task.status)

    # -----------------------------
    # 字体工具
    # -----------------------------

    def applyFont(self, label, size, bold=False):

        font = QFont()
        font.setPointSize(size)
        font.setBold(bold)

        label.setFont(font)

        metrics = QFontMetrics(font)

        # 防止 y g p q j 被裁
        label.setMinimumHeight(metrics.height() + 4)

    # -----------------------------
    # 紧凑模式
    # -----------------------------

    def setCompact(self, compact: bool):

        self.task.compact = compact

        if compact:

            self.setFixedHeight(self.compactHeight)

            self.mainLayout.setContentsMargins(12, 10, 12, 10)
            self.mainLayout.setSpacing(10)

            self.icon.setStyleSheet("font-size:18px;")
            self.grip.setStyleSheet(
                "color:#909399;font-size:14px;"
                "font-weight:bold;background:transparent;"
            )

            self.applyFont(self.nameLabel, 10, True)
            self.applyFont(self.sizeLabel, 8)
            self.applyFont(self.statusLabel, 8)

            self.infoLayout.setSpacing(3)

            if self.task.status == "Compressing":
                self.progress.show()
            else:
                self.progress.hide()

        else:

            self.setFixedHeight(self.normalHeight)

            self.mainLayout.setContentsMargins(18, 14, 18, 14)
            self.mainLayout.setSpacing(14)

            self.icon.setStyleSheet("font-size:22px;")
            self.grip.setStyleSheet(
                "color:#909399;font-size:16px;"
                "font-weight:bold;background:transparent;"
            )

            self.applyFont(self.nameLabel, 12, True)
            self.applyFont(self.sizeLabel, 9)
            self.applyFont(self.statusLabel, 9)

            self.infoLayout.setSpacing(5)

            self.progress.show()

    # -----------------------------
    # 状态更新
    # -----------------------------

    def updateStatus(self, status):

        self.task.status = status

        if (
            status in ("Completed with warnings", "Failed")
            and self.task.error_message
        ):
            self.setToolTip(self.task.error_message)
        else:
            self.setToolTip("")

        color = self.STATUS_COLORS.get(status, "#909399")

        # 直接显示状态文字（Waiting 不再被覆盖）
        self.statusLabel.setText(status)

        self.statusLabel.setStyleSheet(
            f"color:{color};font-weight:600;background:transparent;"
        )

        # 状态切换淡入
        self.fade.stop()
        self.opacity.setOpacity(0.35)
        self.fade.setStartValue(0.35)
        self.fade.setEndValue(1.0)
        self.fade.start()

        # ---------- 垃圾桶：根据状态启用/禁用 ----------
        if status == "Compressing":

            self.removeBtn.setEnabled(False)
            self.removeBtn.setToolTip("Current task can't be removed")
            self.removeBtn.setStyleSheet("""
            ToolButton {
                border: none;
                border-radius: 16px;
                background: transparent;
            }
            """)

            # Start indeterminate; real 7-Zip percentages switch it to 0-100.
            self.progress.setRange(0, 0)
            self.progress.show()

        else:

            self.progress.setRange(0, 100)

            self.removeBtn.setEnabled(not self.queueLocked)
            self.removeBtn.setToolTip("Remove task")
            self.removeBtn.setStyleSheet("""
            ToolButton {
                border: none;
                border-radius: 16px;
                background: transparent;
            }
            ToolButton:hover {
                background: rgba(128,128,128,40);
            }
            ToolButton:pressed {
                background: #E81123;
            }
            """)

        if status in (
            "Completed",
            "Completed with warnings",
            "Failed",
            "Cancelled",
        ):

            self.progress.setValue(
                100
                if status in ("Completed", "Completed with warnings")
                else 0
            )

            if self.task.compact:
                self.progress.hide()

    # -----------------------------
    # 外部调用
    # -----------------------------

    def updateTask(self, task):

        self.task = task

        self.nameLabel.setText(task.name)
        self.sizeLabel.setText(task.size)

        self.progress.setValue(task.progress)

        self.updateStatus(task.status)

    def updateProgress(self, value):

        self.task.progress = value

        if self.progress.maximum() == 0:
            self.progress.setRange(0, 100)

        self.progress.setValue(value)

    def setQueueLocked(self, locked):

        self.queueLocked = locked
        self.removeBtn.setEnabled(
            not locked and self.task.status != "Compressing"
        )

    # -----------------------------
    # 删除动画：左滑 120px + 淡出 180ms
    # -----------------------------

    def startRemoveAnimation(self):

        if self.task.status == "Compressing":
            return

        self.removeBtn.setEnabled(False)

        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)

        fade = QPropertyAnimation(effect, b"opacity", self)
        fade.setDuration(180)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)

        start = self.pos()

        slide = QPropertyAnimation(self, b"pos", self)
        slide.setDuration(180)
        slide.setStartValue(start)
        slide.setEndValue(QPoint(start.x() - 120, start.y()))
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)

        # 持有引用，避免被 GC 提前回收
        self._fade = fade
        self._slide = slide

        slide.finished.connect(
            lambda: self.removeFinished.emit(self.task)
        )

        fade.start()
        slide.start()
