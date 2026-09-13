import os

from PySide6.QtCore import (
    Qt,
    QPropertyAnimation,
    QEasingCurve
)

from PySide6.QtGui import QCloseEvent

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QMessageBox
)

from qfluentwidgets import (
    SubtitleLabel,
    BodyLabel,
    PushButton,
    LineEdit,
    SegmentedWidget,
    FluentIcon,
    setTheme,
    Theme
)

from ui.drop_zone import DropZone
from ui.task_card import TaskCard
from ui.complete_dialog import CompleteDialog

from core.task import Task
from core.compress_thread import CompressThread


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        setTheme(Theme.AUTO)

        self.setWindowTitle("BatchZip")
        self.resize(1100, 700)

        self.tasks = []
        self.cards = []

        self.archiveFormat = "zip"

        self.thread = None
        self.isCompressing = False
        self.isPaused = False

        self.initUI()

    # =====================================================
    # UI
    # =====================================================

    def initUI(self):

        page = QWidget()
        self.setCentralWidget(page)

        self.mainLayout = QVBoxLayout(page)
        self.mainLayout.setContentsMargins(32, 24, 32, 24)
        self.mainLayout.setSpacing(16)

        self.mainLayout.addWidget(
            SubtitleLabel("BatchZip")
        )

        self.mainLayout.addWidget(
            BodyLabel("Batch compress with 7-Zip")
        )

        # 状态栏
        self.statusLabel = BodyLabel("Ready")
        self.mainLayout.addWidget(self.statusLabel)

        # 拖拽区
        self.dropZone = DropZone()
        self.dropZone.filesDropped.connect(
            self.handleFiles
        )

        self.mainLayout.addWidget(self.dropZone)

        # 压缩格式切换
        self.formatSelector = SegmentedWidget()

        self.formatSelector.addItem(
            routeKey="zip",
            text="ZIP",
            onClick=lambda: self.setArchiveFormat("zip")
        )

        self.formatSelector.addItem(
            routeKey="7z",
            text="7Z",
            onClick=lambda: self.setArchiveFormat("7z")
        )

        self.formatSelector.setCurrentItem("zip")

        formatRow = QHBoxLayout()
        formatRow.addWidget(BodyLabel("Format"))
        formatRow.addSpacing(12)
        formatRow.addWidget(self.formatSelector)
        formatRow.addStretch()

        self.mainLayout.addLayout(formatRow)

        # 输出路径
        outputRow = QHBoxLayout()

        self.outputEdit = LineEdit()
        self.outputEdit.setPlaceholderText(
            "Output Folder (leave empty to use original folder)"
        )

        self.browseBtn = PushButton(
            "Browse",
            icon=FluentIcon.FOLDER
        )

        self.browseBtn.clicked.connect(
            self.chooseOutputFolder
        )

        outputRow.addWidget(self.outputEdit)
        outputRow.addWidget(self.browseBtn)

        self.mainLayout.addLayout(outputRow)

        # 按钮
        btnRow = QHBoxLayout()
        btnRow.addStretch()

        self.clearBtn = PushButton(
            "Clear All",
            icon=FluentIcon.DELETE
        )

        self.pauseBtn = PushButton(
            "Pause",
            icon=FluentIcon.PAUSE
        )

        self.pauseBtn.setEnabled(False)

        self.cancelBtn = PushButton("Cancel")
        self.cancelBtn.setEnabled(False)

        self.startBtn = PushButton(
            "Start",
            icon=FluentIcon.PLAY
        )

        self.clearBtn.clicked.connect(
            self.clearTasks
        )

        self.pauseBtn.clicked.connect(
            self.togglePause
        )

        self.cancelBtn.clicked.connect(
            self.cancelCompression
        )

        self.startBtn.clicked.connect(
            self.startCompress
        )

        btnRow.addWidget(self.clearBtn)
        btnRow.addWidget(self.pauseBtn)
        btnRow.addWidget(self.cancelBtn)
        btnRow.addWidget(self.startBtn)

        self.mainLayout.addLayout(btnRow)

        # ============ 任务列表：QListWidget（支持拖拽排序） ============
        self.listWidget = QListWidget()

        self.listWidget.setFrameShape(
            QListWidget.Shape.NoFrame
        )

        self.listWidget.setDragDropMode(
            QListWidget.DragDropMode.InternalMove
        )

        self.listWidget.setDefaultDropAction(
            Qt.DropAction.MoveAction
        )

        self.listWidget.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection
        )

        self.listWidget.setFocusPolicy(
            Qt.FocusPolicy.NoFocus
        )

        self.listWidget.setSpacing(6)

        self.listWidget.setVerticalScrollMode(
            QListWidget.ScrollMode.ScrollPerPixel
        )

        self.listWidget.setStyleSheet("""
        QListWidget {
            background: transparent;
            border: none;
            outline: none;
        }
        QListWidget::item {
            background: transparent;
            border: none;
            padding: 0;
        }
        QListWidget::item:selected {
            background: transparent;
            border: none;
        }
        QListWidget::item:focus {
            outline: none;
        }
        """)

        # 拖拽完成后同步 tasks / cards 顺序
        self.listWidget.model().rowsMoved.connect(
            self.syncTaskOrder
        )

        self.mainLayout.addWidget(
            self.listWidget,
            1
        )

        # 拖拽区动画
        self.dropAnimation = QPropertyAnimation(
            self.dropZone,
            b"maximumHeight",
            self
        )

        self.dropAnimation.setDuration(250)
        self.dropAnimation.setEasingCurve(
            QEasingCurve.Type.OutCubic
        )

    # =====================================================
    # 压缩格式
    # =====================================================

    def setArchiveFormat(self, fmt):

        self.archiveFormat = fmt

    # =====================================================
    # 输出路径
    # =====================================================

    def chooseOutputFolder(self):

        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Output Folder"
        )

        if folder:
            self.outputEdit.setText(folder)

    # =====================================================
    # 添加任务
    # =====================================================

    def handleFiles(self, paths):

        if self.isCompressing:
            return

        existing_paths = {
            os.path.normcase(os.path.abspath(task.path))
            for task in self.tasks
        }
        added = 0
        skipped = 0

        for path in paths:

            normalized = os.path.normcase(os.path.abspath(path))

            if not path or not os.path.exists(path) or normalized in existing_paths:
                skipped += 1
                continue

            task = Task(path)

            card = TaskCard(task)

            # 删除动画结束后才会触发 removeTask
            card.removeFinished.connect(
                self.removeTask
            )

            item = QListWidgetItem()

            # 把 Task 存进 item，用于拖拽丢失 widget 时恢复
            item.setData(
                Qt.ItemDataRole.UserRole,
                task
            )

            item.setSizeHint(card.sizeHint())

            self.listWidget.addItem(item)
            self.listWidget.setItemWidget(item, card)

            self.tasks.append(task)
            self.cards.append(card)

            existing_paths.add(normalized)
            added += 1

        self.updateDensity()

        if skipped:
            self.statusLabel.setText(
                f"Added {added} · Skipped {skipped} invalid or duplicate item(s)"
            )

    # =====================================================
    # 删除单个任务（由 TaskCard 动画结束后触发）
    # =====================================================

    def removeTask(self, task):

        if task not in self.tasks:
            return

        # 当前正在压缩的任务，永远不能删
        if task.status == "Compressing":
            return

        # 压缩期间：仅允许删除 Waiting 任务
        # （删 Completed 任务会让线程迭代器错位，跳过后续任务）
        if self.isCompressing and task.status != "Waiting":
            return

        index = self.tasks.index(task)

        self.tasks.pop(index)
        self.cards.pop(index)

        item = self.listWidget.takeItem(index)
        del item

        # 强制重新布局（修复暂停删除后不补位）
        self.listWidget.doItemsLayout()
        self.listWidget.viewport().update()
        self.listWidget.updateGeometry()

        self.updateDensity()

    # =====================================================
    # 拖拽后同步顺序
    # =====================================================

    def syncTaskOrder(self, *args):

        # 压缩期间不应该触发（拖拽已禁用），双保险
        if self.isCompressing:
            return

        newTasks = []
        newCards = []

        for i in range(self.listWidget.count()):

            item = self.listWidget.item(i)

            if item is None:
                continue

            task = item.data(Qt.ItemDataRole.UserRole)

            if task is None:
                continue

            card = self.listWidget.itemWidget(item)

            # Qt 某些版本在 InternalMove 后会丢失 itemWidget
            # 这里做一次自我修复
            if card is None:
                card = TaskCard(task)
                card.removeFinished.connect(self.removeTask)
                self.listWidget.setItemWidget(item, card)

            # 重新同步尺寸（否则行高会沿用旧值）
            item.setSizeHint(card.sizeHint())

            # 拖拽后重新刷新状态，修复 Waiting 视觉消失
            card.updateStatus(card.task.status)

            newTasks.append(task)
            newCards.append(card)

        self.tasks = newTasks
        self.cards = newCards

        # 触发一次重绘，防止残留
        self.listWidget.viewport().update()

    # =====================================================
    # 开始压缩（后台线程）
    # =====================================================

    def startCompress(self):

        if not self.tasks or self.isCompressing:
            return

        pending_tasks = [
            task
            for task in self.tasks
            if task.status in ("Waiting", "Failed", "Cancelled")
        ]

        if not pending_tasks:
            self.statusLabel.setText("No pending tasks")
            return

        for task in pending_tasks:
            task.status = "Waiting"
            task.progress = 0
            task.error_message = ""

            index = self.tasks.index(task)
            self.cards[index].updateTask(task)

        self.isCompressing = True
        self.isPaused = False

        self.setCompressionControls(True)

        # 压缩期间禁止拖拽（保持队列顺序一致）
        self.listWidget.setDragDropMode(
            QListWidget.DragDropMode.NoDragDrop
        )

        self.thread = CompressThread(
            pending_tasks,
            self.outputEdit.text().strip(),
            self.archiveFormat
        )

        self.thread.taskStarted.connect(self.onTaskStarted)
        self.thread.taskProgress.connect(self.onTaskProgress)
        self.thread.taskFinished.connect(self.onTaskFinished)
        self.thread.taskCancelled.connect(self.onTaskCancelled)
        self.thread.overallStatus.connect(self.statusLabel.setText)
        self.thread.allFinished.connect(self.onAllFinished)
        self.thread.cancelled.connect(self.onCompressionCancelled)
        self.thread.error.connect(self.onWorkerError)
        self.thread.finished.connect(self.onThreadEnded)

        self.thread.start()

    # =====================================================
    # Worker 信号（全部按 Task 对象索引，避免 index 失效）
    # =====================================================

    def onTaskStarted(self, task):

        if task not in self.tasks:
            return

        task.status = "Compressing"

        index = self.tasks.index(task)

        self.cards[index].updateTask(task)

    def onTaskProgress(self, task, percent):

        if task not in self.tasks:
            return

        index = self.tasks.index(task)

        task.progress = percent

        self.cards[index].updateProgress(percent)

    def onTaskFinished(self, task, success):

        if task not in self.tasks:
            return

        index = self.tasks.index(task)

        task.status = (
            "Completed"
            if success
            else "Failed"
        )

        task.progress = (
            100
            if success
            else 0
        )

        self.cards[index].updateTask(task)

        if not success and task.error_message:
            self.cards[index].setToolTip(task.error_message)

    def togglePause(self):

        if not self.thread:
            return

        if self.isPaused:

            self.thread.resume()

            self.pauseBtn.setText("Pause")
            self.pauseBtn.setIcon(FluentIcon.PAUSE)

            self.isPaused = False

        else:

            self.thread.pause()

            self.pauseBtn.setText("Resume")
            self.pauseBtn.setIcon(FluentIcon.PLAY)

            self.isPaused = True

    def cancelCompression(self):

        if not self.thread or not self.thread.isRunning():
            return

        reply = QMessageBox.question(
            self,
            "BatchZip",
            "Cancel the current compression?\n\nThe incomplete archive will be removed.",
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        self.statusLabel.setText("Cancelling...")
        self.pauseBtn.setEnabled(False)
        self.cancelBtn.setEnabled(False)
        self.thread.cancel()

    def onTaskCancelled(self, task):

        if task not in self.tasks:
            return

        task.status = "Cancelled"
        task.progress = 0

        index = self.tasks.index(task)
        self.cards[index].updateTask(task)

    def onCompressionCancelled(self):

        self.isCompressing = False
        self.isPaused = False
        self.setCompressionControls(False)

        self.pauseBtn.setText("Pause")
        self.pauseBtn.setIcon(FluentIcon.PAUSE)
        self.statusLabel.setText("Cancelled")

        self.listWidget.setDragDropMode(
            QListWidget.DragDropMode.InternalMove
        )

    def onAllFinished(self, success, failed, folder):

        self.isCompressing = False
        self.isPaused = False

        self.setCompressionControls(False)

        self.pauseBtn.setText("Pause")
        self.pauseBtn.setIcon(FluentIcon.PAUSE)

        self.statusLabel.setText(
            "Completed" if failed == 0 else f"Completed with {failed} failure(s)"
        )

        # 恢复拖拽
        self.listWidget.setDragDropMode(
            QListWidget.DragDropMode.InternalMove
        )

        self.showCompleteDialog(success, failed, folder)

    def onWorkerError(self, message):

        self.isCompressing = False
        self.isPaused = False

        self.setCompressionControls(False)

        for task, card in zip(self.tasks, self.cards):
            if task.status == "Compressing":
                task.status = "Failed"
                task.progress = 0
                task.error_message = message
                card.updateTask(task)
                card.setToolTip(message)

        # 恢复拖拽
        self.listWidget.setDragDropMode(
            QListWidget.DragDropMode.InternalMove
        )

        QMessageBox.critical(
            self,
            "BatchZip",
            message
        )

    def onThreadEnded(self):

        finished_thread = self.sender()

        if finished_thread is not None:
            finished_thread.deleteLater()

        if self.thread is finished_thread:
            self.thread = None

    def setCompressionControls(self, running):

        self.startBtn.setEnabled(not running)
        self.pauseBtn.setEnabled(running)
        self.cancelBtn.setEnabled(running)
        self.clearBtn.setEnabled(not running)
        self.outputEdit.setEnabled(not running)
        self.browseBtn.setEnabled(not running)
        self.formatSelector.setEnabled(not running)
        self.dropZone.setEnabled(not running)

        for card in self.cards:
            card.setQueueLocked(running)

    # =====================================================
    # 完成弹窗
    # =====================================================

    def showCompleteDialog(
        self,
        success,
        failed,
        folder
    ):

        dialog = CompleteDialog(
            success,
            failed,
            folder
        )

        dialog.exec()

    # =====================================================
    # 清空任务
    # =====================================================

    def clearTasks(self):

        if self.isCompressing:
            return

        self.listWidget.clear()

        self.tasks.clear()
        self.cards.clear()

        self.updateDensity()

    # =====================================================
    # 拖拽区动画
    # =====================================================

    def animateDropZone(self, height):

        if self.dropZone.maximumHeight() == height:
            return

        self.dropAnimation.stop()

        self.dropAnimation.setStartValue(
            self.dropZone.maximumHeight()
        )

        self.dropAnimation.setEndValue(height)

        self.dropAnimation.start()

    # =====================================================
    # 自动切换紧凑模式
    # =====================================================

    def updateDensity(self):

        count = self.listWidget.count()

        if count == 0:
            height = 300
            compact = False

        elif count < 5:
            height = 180
            compact = False

        else:
            height = 140
            compact = True

        self.dropZone.updateQueueCount(count)

        self.animateDropZone(height)

        for i in range(self.listWidget.count()):

            item = self.listWidget.item(i)

            if item is None:
                continue

            card = self.listWidget.itemWidget(item)

            if card is None:
                continue

            card.setCompact(compact)

            # 高度变了同步 sizeHint，否则列表会留空
            item.setSizeHint(card.sizeHint())

    # =====================================================
    # 关闭窗口：安全收尾后台线程
    # =====================================================

    def closeEvent(self, event: QCloseEvent):

        if self.thread and self.thread.isRunning():

            reply = QMessageBox.question(
                self,
                "BatchZip",
                "Compression is still running.\n\nStop compression and exit?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return

            self.thread.stop()
            self.thread.wait()

        event.accept()
