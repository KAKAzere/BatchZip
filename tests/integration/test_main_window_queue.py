"""Production integration tests for the MainWindow task queue.

These lock the Phase E single-authority cutover in place:

* ``TaskQueueModel`` is the only membership / ordering / identity authority;
* ``TaskQueueView`` + ``TaskQueueDelegate`` are the only rendering path;
* ``TaskQueueController`` is the only runtime worker-update seam;
* MainWindow keeps session policy (queue freeze, Clear All gating, Pause).

They also assert the legacy production path does not grow back: no
``QListWidget`` storage, no per-row QWidget embedded in the queue, no
``syncTaskOrder``, no second task container, no second wheel driver, and no
import of the retired ``ui.task_card`` module.

Scoped to production wiring and observable behaviour; the isolated
Model/View/Delegate behaviour lives in the queue focused test modules.
"""

import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, Signal, Qt
from PySide6.QtGui import QPainter, QPixmap, QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QListWidget,
    QStyleOptionViewItem,
    QWidget,
)

import ui.main_window as main_window
from core.task import Task
from ui.main_window import MainWindow
from ui.task_delegate import TaskQueueDelegate
from ui.task_model import TaskQueueModel
from ui.task_queue_controller import TaskQueueController
from ui.task_queue_view import TaskQueueView

REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeCompressThread(QObject):
    """Records the session snapshot and pause/resume calls without running 7-Zip."""

    taskStarted = Signal(object)
    taskProgress = Signal(object, int)
    taskFinished = Signal(object, str)
    taskCancelled = Signal(object)
    overallStatus = Signal(str)
    allFinished = Signal(int, int, int, str)
    cancelled = Signal()
    error = Signal(str)
    finished = Signal()

    def __init__(self, tasks, output_folder, archive_format="zip"):
        super().__init__()
        self.tasks = list(tasks)
        self.output_folder = output_folder
        self.archive_format = archive_format
        self.stop_error = ""
        self.paused = False
        self.start_calls = 0
        self.pause_calls = 0
        self.resume_calls = 0
        self.cancel_calls = 0

    def start(self):
        self.start_calls += 1

    def isRunning(self):
        return False

    def pause(self):
        self.pause_calls += 1
        self.paused = True

    def resume(self):
        self.resume_calls += 1
        self.paused = False

    def cancel(self):
        self.cancel_calls += 1

    def stop(self):
        pass


class MainWindowQueueTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.window = MainWindow()
        self.window.resize(1000, 700)
        self.window.show()
        self.app.processEvents()
        self.model = self.window.queueModel
        self.view = self.window.queueView
        self.addCleanup(self._teardown)

    def _teardown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    # ------------------------------------------------------- architecture

    def assertNoPerRowWidgets(self):
        """The queue renders through the delegate: no per-row QWidget may exist."""
        for row in range(self.model.rowCount()):
            self.assertIsNone(self.view.indexWidget(self.model.index(row)), row)
        self.assertEqual(
            [w for w in self.view.findChildren(QWidget)
             if w.objectName() == "taskCard"],
            [],
        )

    def queueWidgetCount(self):
        return len(self.view.viewport().findChildren(QWidget))
        self._temp.cleanup()

    # ---------------------------------------------------------------- helpers

    def make_files(self, names):
        paths = []
        for name in names:
            path = self.root / name
            path.write_text("x", encoding="utf-8")
            paths.append(str(path))
        return paths

    def enqueue(self, names):
        self.window.handleFiles(self.make_files(names))
        self.app.processEvents()
        return list(self.model.ordered_tasks())

    def enqueue_default(self):
        return self.enqueue(("one.txt", "two.txt", "three.txt"))

    def started_task(self, index=0):
        task = self.enqueue_default()[index]
        self.window.onTaskStarted(task)
        self.app.processEvents()
        return task

    def delete_point(self, row):
        rect = self.view.visualRect(self.model.index(row))
        return QPoint(rect.right() - 28, rect.center().y())

    def click_delete(self, row):
        QTest.mouseClick(self.view.viewport(), Qt.MouseButton.LeftButton,
                         pos=self.delete_point(row))
        self.app.processEvents()

    def drop_after(self, row):
        rect = self.view.visualRect(self.model.index(row))
        if self.view._grid:
            return QPoint(rect.left() + rect.width() * 3 // 4, rect.center().y())
        return QPoint(rect.center().x(), rect.top() + rect.height() * 3 // 4)

    def drag(self, source_row, dest_point):
        source = self.view.visualRect(self.model.index(source_row)).center()
        QTest.mousePress(self.view.viewport(), Qt.MouseButton.LeftButton, pos=source)
        QTest.mouseMove(self.view.viewport(), dest_point)
        QTest.mouseRelease(self.view.viewport(), Qt.MouseButton.LeftButton, pos=dest_point)
        self.app.processEvents()

    def wheel_event(self, angle=-120, pixel=None):
        return QWheelEvent(QPointF(10, 10), QPointF(10, 10), pixel or QPoint(),
                           QPoint(0, angle), Qt.NoButton, Qt.NoModifier,
                           Qt.ScrollUpdate, False)

    def start_compression(self):
        with patch.object(main_window, "CompressThread", FakeCompressThread):
            self.window.startCompress()
        self.app.processEvents()
        return self.window.thread

    def freeze_queue(self):
        self.window.setCompressionControls(True)
        self.app.processEvents()

    def release_queue(self):
        self.window.setCompressionControls(False)
        self.app.processEvents()

    def task_ids(self, tasks):
        return [id(task) for task in tasks]


class MainWindowConstructionTests(MainWindowQueueTestCase):
    def test_main_window_uses_queue_model_view_and_controller(self):
        self.assertIsInstance(self.window.queueModel, TaskQueueModel)
        self.assertIsInstance(self.window.queueView, TaskQueueView)
        self.assertIsInstance(self.window.queueController, TaskQueueController)
        self.assertIs(self.view.model(), self.model)

    def test_controller_is_bound_to_the_production_model_and_view(self):
        self.window.queueController.set_paused(True)
        self.assertIs(self.view.itemDelegate().paused, True)
        self.window.queueController.set_paused(False)

        self.enqueue_default()
        task = self.model.task_at(0)
        self.window.queueController.on_task_started(task)
        self.assertEqual(
            self.model.data(self.model.index(0), TaskQueueModel.StatusRole),
            "Compressing",
        )

    def test_main_window_holds_no_legacy_queue_state(self):
        for name in ("tasks", "cards", "listWidget",
                     "_wheelTarget", "_wheelTimer", "_wheelClock", "_wheelStart"):
            self.assertFalse(hasattr(self.window, name), name)

    def test_main_window_holds_no_legacy_queue_methods(self):
        for name in ("syncTaskOrder", "removeTask", "_applyQueueView",
                     "updateGridGeometry", "_stopQueueScroll", "_advanceQueueScroll"):
            self.assertFalse(hasattr(MainWindow, name), name)

    def test_production_uses_model_view_delegate_without_per_row_widgets(self):
        self.enqueue_default()
        self.assertEqual(self.window.findChildren(QListWidget), [])
        self.assertIsInstance(self.view.model(), TaskQueueModel)
        self.assertIsInstance(self.view.itemDelegate(), TaskQueueDelegate)
        self.assertNoPerRowWidgets()
        self.assertEqual(
            [w for w in self.window.findChildren(QWidget)
             if w.objectName() == "taskCard"],
            [],
        )

    def test_production_modules_do_not_import_the_retired_task_card_module(self):
        offenders = []
        for path in sorted((REPO_ROOT / "ui").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "ui.task_card":
                    offenders.append((path.name, node.lineno))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("ui.task_card"):
                            offenders.append((path.name, node.lineno))
        self.assertEqual(offenders, [])

    def test_main_window_holds_no_second_task_container(self):
        self.enqueue_default()
        containers = []
        for name, value in vars(self.window).items():
            if isinstance(value, Task):
                containers.append(name)
            elif isinstance(value, (list, tuple, set)):
                if any(isinstance(item, Task) for item in value):
                    containers.append(name)
            elif isinstance(value, dict):
                if any(isinstance(item, Task) for item in value.values()):
                    containers.append(name)
        self.assertEqual(containers, [])
        self.assertEqual(self.model.rowCount(), 3)


class SingleScrollDriverTests(MainWindowQueueTestCase):
    def test_production_has_single_scroll_driver(self):
        for name in ("_wheelTarget", "_wheelTimer", "_wheelClock", "_wheelStart"):
            self.assertFalse(hasattr(self.window, name), name)
        self.assertTrue(hasattr(self.view, "_wheel_timer"))
        self.assertTrue(hasattr(self.view, "_wheel_clock"))

    def test_main_window_event_filter_does_not_consume_wheel_events(self):
        self.assertFalse(
            self.window.eventFilter(self.view.viewport(), self.wheel_event())
        )

    def test_wheel_scrolling_runs_through_the_view_driver(self):
        self.enqueue(tuple("file%03d.txt" % i for i in range(40)))
        bar = self.view.verticalScrollBar()
        bar.setValue(0)
        self.app.processEvents()

        self.view.wheelEvent(self.wheel_event())
        for _ in range(30):
            QTest.qWait(10)

        self.assertGreater(bar.value(), 0)
        self.assertFalse(self.view._wheel_timer.isActive())


class HandleFilesIntegrationTests(MainWindowQueueTestCase):
    def test_handle_files_enqueues_into_queue_model(self):
        paths = self.make_files(("a.txt", "b.txt", "c.txt"))
        self.window.handleFiles(paths)

        self.assertEqual(self.model.rowCount(), 3)
        self.assertEqual(
            [task.name for task in self.model.ordered_tasks()],
            ["a.txt", "b.txt", "c.txt"],
        )
        self.assertEqual(self.window.queueTitle.text(), "Task Queue (3)")

    def test_handle_files_deduplicates_normalized_paths(self):
        paths = self.make_files(("a.txt", "b.txt"))
        self.window.handleFiles(paths)
        self.window.handleFiles(paths)
        self.window.handleFiles([path.replace(os.sep, "/") for path in paths])

        self.assertEqual(self.model.rowCount(), 2)

    def test_handle_files_skips_missing_paths(self):
        self.window.handleFiles([str(self.root / "missing.txt")])

        self.assertEqual(self.model.rowCount(), 0)
        self.assertEqual(self.model.ordered_tasks(), ())

    def test_handle_files_sorts_multiple_files_naturally(self):
        paths = self.make_files(("f10.txt", "f2.txt", "f1.txt"))
        self.window.handleFiles(paths)

        self.assertEqual(
            [task.name for task in self.model.ordered_tasks()],
            ["f1.txt", "f2.txt", "f10.txt"],
        )

    def test_handle_files_keeps_existing_task_identity(self):
        first = self.enqueue(("a.txt", "b.txt"))
        ids = self.task_ids(first)

        self.window.handleFiles(self.make_files(("c.txt",)))
        ordered = list(self.model.ordered_tasks())

        self.assertEqual(self.model.rowCount(), 3)
        self.assertEqual(self.task_ids(ordered[:2]), ids)


class QueueAuthorityTests(MainWindowQueueTestCase):
    def test_queue_model_is_the_only_membership_authority(self):
        tasks = self.enqueue_default()
        self.assertEqual(self.model.rowCount(), 3)

        self.click_delete(1)
        self.assertEqual(self.model.rowCount(), 2)
        self.assertEqual(
            self.model.ordered_tasks(), (tasks[0], tasks[2])
        )
        self.assertEqual(self.task_ids(self.model.ordered_tasks()),
                         self.task_ids([tasks[0], tasks[2]]))

    def test_reorder_uses_move_rows_without_remove_or_insert(self):
        tasks = self.enqueue_default()
        moved = QSignalSpy(self.model.rowsMoved)
        removed = QSignalSpy(self.model.rowsRemoved)
        inserted = QSignalSpy(self.model.rowsInserted)
        reset = QSignalSpy(self.model.modelReset)

        self.drag(0, self.drop_after(2))

        self.assertEqual(moved.count(), 1)
        self.assertEqual(removed.count(), 0)
        self.assertEqual(inserted.count(), 0)
        self.assertEqual(reset.count(), 0)
        self.assertEqual(
            self.model.ordered_tasks(), (tasks[1], tasks[2], tasks[0])
        )
        self.assertEqual(sorted(self.task_ids(self.model.ordered_tasks())),
                         sorted(self.task_ids(tasks)))

    def test_clear_all_empties_only_the_model(self):
        self.enqueue_default()
        reset = QSignalSpy(self.model.modelReset)

        self.window.clearTasks()
        self.app.processEvents()

        self.assertEqual(self.model.rowCount(), 0)
        self.assertEqual(self.model.ordered_tasks(), ())
        self.assertEqual(reset.count(), 0)


class StartCompressionSnapshotTests(MainWindowQueueTestCase):
    def test_start_compress_uses_model_order(self):
        tasks = self.enqueue(("a.txt", "b.txt", "c.txt", "d.txt"))
        tasks[1].status = "Completed"
        tasks[3].status = "Completed with warnings"
        thread = self.start_compression()

        self.assertIsInstance(thread, FakeCompressThread)
        self.assertEqual(
            self.task_ids(thread.tasks), self.task_ids([tasks[0], tasks[2]])
        )

    def test_start_compress_skips_completed_and_compressing_tasks(self):
        tasks = self.enqueue(("a.txt", "b.txt", "c.txt", "d.txt", "e.txt"))
        for task, status in zip(tasks, ("Completed", "Compressing",
                                        "Waiting", "Failed", "Cancelled")):
            task.status = status

        thread = self.start_compression()

        self.assertEqual(
            self.task_ids(thread.tasks), self.task_ids([tasks[2], tasks[3], tasks[4]])
        )

    def test_start_compress_resets_pending_tasks_to_waiting(self):
        tasks = self.enqueue(("a.txt", "b.txt"))
        tasks[0].status = "Failed"
        tasks[0].progress = 80
        tasks[0].error_message = "old failure"
        tasks[1].status = "Cancelled"

        self.start_compression()

        for task in tasks:
            self.assertEqual(task.status, "Waiting")
            self.assertEqual(task.progress, 0)
            self.assertEqual(task.error_message, "")

    def test_worker_snapshot_is_not_a_second_order_authority(self):
        tasks = self.enqueue(("a.txt", "b.txt", "c.txt"))
        thread = self.start_compression()

        self.assertEqual(self.task_ids(thread.tasks), self.task_ids(tasks))
        thread.tasks.clear()
        self.assertEqual(self.model.rowCount(), 3)
        self.assertEqual(self.task_ids(self.model.ordered_tasks()),
                         self.task_ids(tasks))
        self.assertTrue(self.window.isCompressing)


class QueueFreezeTests(MainWindowQueueTestCase):
    def test_queue_lock_blocks_delete_and_reorder(self):
        tasks = self.enqueue_default()
        self.freeze_queue()
        order_before = self.task_ids(self.model.ordered_tasks())
        moved = QSignalSpy(self.model.rowsMoved)
        reset = QSignalSpy(self.model.modelReset)

        self.click_delete(1)
        self.drag(0, self.drop_after(2))

        self.assertEqual(self.model.rowCount(), 3)
        self.assertEqual(self.task_ids(self.model.ordered_tasks()), order_before)
        self.assertEqual(moved.count(), 0)
        self.assertEqual(reset.count(), 0)
        self.assertEqual(self.task_ids(self.model.ordered_tasks()),
                         self.task_ids(tasks))

    def test_queue_lock_does_not_touch_task_state_or_emit_updates(self):
        self.started_task(0)
        snapshot = [(task.status, task.progress, task.error_message)
                    for task in self.model.ordered_tasks()]
        changed = QSignalSpy(self.model.dataChanged)
        reset = QSignalSpy(self.model.modelReset)

        self.freeze_queue()
        self.release_queue()

        self.assertEqual(
            [(task.status, task.progress, task.error_message)
             for task in self.model.ordered_tasks()],
            snapshot,
        )
        self.assertEqual(changed.count(), 0)
        self.assertEqual(reset.count(), 0)

    def test_queue_lock_preserves_wheel_scrolling(self):
        self.enqueue(tuple("file%03d.txt" % i for i in range(40)))
        bar = self.view.verticalScrollBar()
        bar.setValue(0)
        self.freeze_queue()

        self.view.wheelEvent(self.wheel_event())
        for _ in range(30):
            QTest.qWait(10)

        self.assertGreater(bar.value(), 0)

    def test_queue_lock_clears_a_drag_in_progress(self):
        self.enqueue_default()
        viewport = self.view.viewport()
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton,
                         pos=self.view.visualRect(self.model.index(0)).center())
        QTest.mouseMove(viewport, self.view.visualRect(self.model.index(2)).center())
        self.app.processEvents()
        self.assertIsNotNone(self.view._drag_task)
        moved = QSignalSpy(self.model.rowsMoved)

        self.freeze_queue()
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton,
                           pos=self.view.visualRect(self.model.index(2)).center())
        self.app.processEvents()

        self.assertIsNone(self.view._drag_task)
        self.assertIsNone(self.view._drag_origin)
        self.assertFalse(self.view._dragging)
        self.assertEqual(moved.count(), 0)

    def test_queue_lock_clears_a_delete_press_in_progress(self):
        self.enqueue_default()
        viewport = self.view.viewport()
        victim = self.model.task_at(1)

        QTest.mousePress(viewport, Qt.MouseButton.LeftButton,
                         pos=self.delete_point(1))
        self.assertIs(self.view._delete_press_task, victim)

        self.freeze_queue()
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton,
                           pos=self.delete_point(1))
        self.app.processEvents()

        self.assertIsNone(self.view._delete_press_task)
        self.assertEqual(self.model.row_for_task(victim), 1)

    def test_queue_lock_toggle_is_idempotent(self):
        self.enqueue_default()
        changed = QSignalSpy(self.model.dataChanged)
        reset = QSignalSpy(self.model.modelReset)
        order_before = self.task_ids(self.model.ordered_tasks())

        for _ in range(3):
            self.window.setCompressionControls(True)
            self.window.setCompressionControls(True)
            self.window.setCompressionControls(False)
            self.window.setCompressionControls(False)

        self.assertEqual(changed.count(), 0)
        self.assertEqual(reset.count(), 0)
        self.assertEqual(self.task_ids(self.model.ordered_tasks()), order_before)


class QueueUnlockRecoveryTests(MainWindowQueueTestCase):
    def test_unlock_restores_delete(self):
        self.enqueue_default()
        self.freeze_queue()
        self.release_queue()

        victim = self.model.task_at(1)
        self.click_delete(1)

        self.assertEqual(self.model.row_for_task(victim), -1)
        self.assertEqual(self.model.rowCount(), 2)

    def test_unlock_restores_reorder_without_rebinding(self):
        tasks = self.enqueue_default()
        model_before = self.view.model()
        self.freeze_queue()
        self.release_queue()
        moved = QSignalSpy(self.model.rowsMoved)

        self.drag(0, self.drop_after(2))

        self.assertIs(self.view.model(), model_before)
        self.assertEqual(moved.count(), 1)
        self.assertEqual(
            self.model.ordered_tasks(), (tasks[1], tasks[2], tasks[0])
        )


class ControllerRuntimeIntegrationTests(MainWindowQueueTestCase):
    def test_started_publishes_compressing_state(self):
        tasks = self.enqueue_default()
        changed = QSignalSpy(self.model.dataChanged)
        reset = QSignalSpy(self.model.modelReset)

        self.window.onTaskStarted(tasks[1])

        index = self.model.index(1)
        self.assertEqual(tasks[1].status, "Compressing")
        self.assertEqual(self.model.data(index, TaskQueueModel.StatusRole),
                         "Compressing")
        self.assertEqual(self.model.data(index, TaskQueueModel.DisplayStatusRole),
                         "Compressing")
        self.assertFalse(self.model.data(index, TaskQueueModel.DeletableRole))
        self.assertEqual(changed.count(), 1)
        self.assertEqual(changed.at(0)[0].row(), 1)
        self.assertEqual(reset.count(), 0)
        self.assertEqual(self.model.task_at(0).status, "Waiting")
        self.assertEqual(self.model.task_at(2).status, "Waiting")

    def test_progress_updates_only_the_target_task(self):
        task = self.started_task(1)
        changed = QSignalSpy(self.model.dataChanged)
        reset = QSignalSpy(self.model.modelReset)
        order_before = self.task_ids(self.model.ordered_tasks())

        self.window.onTaskProgress(task, 42)

        self.assertEqual(task.progress, 42)
        self.assertEqual(
            self.model.data(self.model.index(1), TaskQueueModel.ProgressRole), 42
        )
        self.assertEqual([t.progress for t in self.model.ordered_tasks()],
                         [0, 42, 0])
        self.assertEqual(changed.count(), 1)
        self.assertEqual(changed.at(0)[0].row(), 1)
        self.assertEqual(list(changed.at(0)[2]),
                         [TaskQueueModel.ProgressRole])
        self.assertEqual(self.task_ids(self.model.ordered_tasks()), order_before)
        self.assertEqual(reset.count(), 0)

    def _terminal(self, result, message=""):
        task = self.started_task(1)
        task.error_message = message
        reset = QSignalSpy(self.model.modelReset)
        order_before = self.task_ids(self.model.ordered_tasks())
        if result == "Cancelled":
            self.window.onTaskCancelled(task)
        else:
            self.window.onTaskFinished(task, result)
        return task, reset, order_before

    def test_completed_terminal_publishes_progress_100(self):
        task, reset, order_before = self._terminal("Completed")

        index = self.model.index(1)
        self.assertEqual(task.status, "Completed")
        self.assertEqual(task.progress, 100)
        self.assertEqual(self.model.data(index, TaskQueueModel.StatusRole),
                         "Completed")
        self.assertTrue(self.model.data(index, TaskQueueModel.DeletableRole))
        self.assertEqual(self.task_ids(self.model.ordered_tasks()), order_before)
        self.assertEqual(reset.count(), 0)

    def test_warning_terminal_is_not_normalized_to_completed(self):
        task, reset, order_before = self._terminal(
            "Completed with warnings", message="partial result"
        )

        index = self.model.index(1)
        self.assertEqual(task.status, "Completed with warnings")
        self.assertEqual(task.progress, 100)
        self.assertEqual(self.model.data(index, TaskQueueModel.StatusRole),
                         "Completed with warnings")
        self.assertEqual(self.model.data(index, TaskQueueModel.DisplayStatusRole),
                         "Warning")
        self.assertTrue(self.model.data(index, TaskQueueModel.DeletableRole))
        self.assertEqual(self.task_ids(self.model.ordered_tasks()), order_before)
        self.assertEqual(reset.count(), 0)

    def test_failed_terminal_publishes_progress_0(self):
        task, reset, order_before = self._terminal("Failed", message="boom")

        index = self.model.index(1)
        self.assertEqual(task.status, "Failed")
        self.assertEqual(task.progress, 0)
        self.assertTrue(self.model.data(index, TaskQueueModel.DeletableRole))
        self.assertEqual(self.task_ids(self.model.ordered_tasks()), order_before)
        self.assertEqual(reset.count(), 0)

    def test_cancelled_terminal_publishes_progress_0(self):
        task, reset, order_before = self._terminal("Cancelled")

        index = self.model.index(1)
        self.assertEqual(task.status, "Cancelled")
        self.assertEqual(task.progress, 0)
        self.assertTrue(self.model.data(index, TaskQueueModel.DeletableRole))
        self.assertEqual(self.task_ids(self.model.ordered_tasks()), order_before)
        self.assertEqual(reset.count(), 0)

    def test_terminal_publishes_error_and_tooltip_roles(self):
        task, _, _ = self._terminal("Failed", message="disk full")
        index = self.model.index(1)

        self.assertEqual(self.model.data(index, TaskQueueModel.ErrorRole),
                         "disk full")
        self.assertEqual(
            self.model.data(index, Qt.ItemDataRole.ToolTipRole), "disk full"
        )

        task.status = "Compressing"
        task.error_message = ""
        self.window.onTaskFinished(task, "Completed")
        self.assertEqual(self.model.data(index, TaskQueueModel.ErrorRole), "")
        self.assertEqual(
            self.model.data(index, Qt.ItemDataRole.ToolTipRole), task.path
        )

    def test_worker_error_publishes_failed_state(self):
        tasks = self.enqueue_default()
        running = tasks[1]
        untouched = tasks[2]
        self.window.onTaskStarted(running)
        self.window.onTaskStarted(untouched)
        self.window.onTaskFinished(untouched, "Completed")

        with patch.object(main_window.QMessageBox, "critical"):
            self.window.onWorkerError("worker exploded")

        index = self.model.index(1)
        self.assertEqual(running.status, "Failed")
        self.assertEqual(running.progress, 0)
        self.assertEqual(running.error_message, "worker exploded")
        self.assertEqual(self.model.data(index, TaskQueueModel.ErrorRole),
                         "worker exploded")
        self.assertEqual(
            self.model.data(index, Qt.ItemDataRole.ToolTipRole), "worker exploded"
        )
        self.assertEqual(untouched.status, "Completed")
        self.assertEqual(untouched.error_message, "")
        self.assertFalse(self.window.isCompressing)


class PauseResumeIntegrationTests(MainWindowQueueTestCase):
    def test_pause_is_presentation_only(self):
        self.enqueue_default()
        thread = self.start_compression()
        task = thread.tasks[0]
        self.window.onTaskStarted(task)
        self.app.processEvents()
        row = self.model.row_for_task(task)
        changed = QSignalSpy(self.model.dataChanged)
        reset = QSignalSpy(self.model.modelReset)

        self.window.togglePause()
        self.app.processEvents()

        index = self.model.index(row)
        self.assertTrue(self.window.isPaused)
        self.assertEqual(thread.pause_calls, 1)
        self.assertIs(self.view.itemDelegate().paused, True)
        self.assertEqual(task.status, "Compressing")
        self.assertEqual(self.model.data(index, TaskQueueModel.StatusRole),
                         "Compressing")
        self.assertEqual(self.model.data(index, TaskQueueModel.DisplayStatusRole),
                         "Compressing")
        self.assertFalse(self.model.data(index, TaskQueueModel.DeletableRole))
        self.assertEqual(changed.count(), 0)
        self.assertEqual(reset.count(), 0)

    def test_resume_restores_presentation_without_business_roundtrip(self):
        self.enqueue_default()
        thread = self.start_compression()
        task = thread.tasks[0]
        self.window.onTaskStarted(task)
        self.window.togglePause()
        self.app.processEvents()

        self.window.togglePause()
        self.app.processEvents()

        self.assertFalse(self.window.isPaused)
        self.assertEqual(thread.resume_calls, 1)
        self.assertIs(self.view.itemDelegate().paused, False)
        self.assertEqual(task.status, "Compressing")

    def test_pause_preserves_progress(self):
        self.enqueue_default()
        thread = self.start_compression()
        task = thread.tasks[0]
        self.window.onTaskStarted(task)
        self.window.onTaskProgress(task, 55)

        self.window.togglePause()
        self.window.togglePause()
        self.app.processEvents()

        self.assertEqual(task.progress, 55)
        self.assertEqual(
            self.model.data(self.model.index(self.model.row_for_task(task)),
                            TaskQueueModel.ProgressRole),
            55,
        )


class SessionStateSeamTests(MainWindowQueueTestCase):
    """Lock the MainWindow session-state seams in place.

    ``_set_compression_session_active`` keeps ``isCompressing`` and the View
    queue lock in step; ``_set_session_paused`` keeps ``isPaused`` and the
    Delegate paused presentation in step. Both must stay the only transition
    writers so no caller has to remember to update two fields.
    """

    def rendered_status(self, task):
        """Capture the status the delegate actually computes for one row."""
        delegate = self.view.itemDelegate()
        row = self.model.row_for_task(task)
        captured = []
        original = delegate._draw_card

        def spy(painter, option_rect, compact, dark, raw, status, *rest):
            captured.append((raw, status))
            return original(painter, option_rect, compact, dark, raw, status, *rest)

        delegate._draw_card = spy
        try:
            option = QStyleOptionViewItem()
            option.rect = QRect(0, 0, 400, 60)
            surface = QPixmap(420, 80)
            surface.fill(Qt.GlobalColor.white)
            painter = QPainter(surface)
            try:
                delegate.paint(painter, option, self.model.index(row))
            finally:
                painter.end()
        finally:
            delegate._draw_card = original
        self.assertTrue(captured, "delegate did not render the row")
        return captured[0]

    def finish_session(self, kind):
        if kind == "finish":
            with patch.object(main_window, "CompleteDialog"), \
                    patch.object(main_window, "WarningArchiveDialog"):
                self.window.onAllFinished(1, 0, 0, str(self.root))
        elif kind == "cancel":
            self.window.onCompressionCancelled()
        else:
            with patch.object(main_window.QMessageBox, "critical"):
                self.window.onWorkerError("worker exploded")
        self.app.processEvents()

    def assertSessionActiveInStep(self):
        self.assertTrue(self.window.isCompressing)
        self.assertIs(self.view._queue_locked, True)
        self.assertEqual(self.window.isCompressing, self.view._queue_locked)

    def assertSessionIdleInStep(self):
        self.assertFalse(self.window.isCompressing)
        self.assertIs(self.view._queue_locked, False)
        self.assertEqual(self.window.isCompressing, self.view._queue_locked)

    def test_session_active_invariant_holds_across_cancel_sequence(self):
        self.enqueue_default()
        self.assertSessionIdleInStep()

        thread = self.start_compression()
        self.assertSessionActiveInStep()

        task = thread.tasks[0]
        self.window.onTaskStarted(task)
        self.window.togglePause()
        self.app.processEvents()
        self.assertSessionActiveInStep()

        self.window.cancelCompression()
        self.app.processEvents()
        self.assertSessionActiveInStep()

        self.finish_session("cancel")
        self.assertSessionIdleInStep()

    def test_session_active_invariant_holds_on_finish_and_error(self):
        for kind in ("finish", "error"):
            with self.subTest(kind=kind):
                self.enqueue_default()
                self.start_compression()
                self.assertSessionActiveInStep()

                self.finish_session(kind)
                self.assertSessionIdleInStep()

                self.window.clearTasks()
                self.app.processEvents()

    def test_pause_presentation_clears_on_cancel(self):
        self.enqueue_default()
        thread = self.start_compression()
        self.window.onTaskStarted(thread.tasks[0])
        self.window.togglePause()
        self.app.processEvents()
        self.assertTrue(self.view.itemDelegate().paused)

        self.finish_session("cancel")

        self.assertFalse(self.window.isPaused)
        self.assertIs(self.view.itemDelegate().paused, False)

    def test_pause_presentation_clears_on_normal_finish(self):
        self.enqueue_default()
        thread = self.start_compression()
        self.window.onTaskStarted(thread.tasks[0])
        self.window.togglePause()
        self.app.processEvents()
        self.assertTrue(self.view.itemDelegate().paused)

        self.finish_session("finish")

        self.assertFalse(self.window.isPaused)
        self.assertIs(self.view.itemDelegate().paused, False)

    def test_pause_presentation_clears_on_worker_error(self):
        self.enqueue_default()
        thread = self.start_compression()
        self.window.onTaskStarted(thread.tasks[0])
        self.window.togglePause()
        self.app.processEvents()
        self.assertTrue(self.view.itemDelegate().paused)

        self.finish_session("error")

        self.assertFalse(self.window.isPaused)
        self.assertIs(self.view.itemDelegate().paused, False)

    def test_pause_cancel_restart_does_not_leak_paused_presentation(self):
        """Regression: pause -> cancel -> restart must not paint Compressing as Paused."""
        self.enqueue_default()
        self.start_compression()
        first = self.model.task_at(0)
        self.window.onTaskStarted(first)
        self.window.togglePause()
        self.app.processEvents()
        self.assertTrue(self.window.isPaused)

        self.window.cancelCompression()
        self.app.processEvents()
        self.finish_session("cancel")
        self.assertFalse(self.window.isPaused)
        self.assertIs(self.view.itemDelegate().paused, False)

        self.start_compression()
        second = self.model.task_at(0)
        self.window.onTaskStarted(second)
        self.app.processEvents()

        raw, status = self.rendered_status(second)
        self.assertFalse(self.window.isPaused)
        self.assertIs(self.view.itemDelegate().paused, False)
        self.assertEqual(second.status, "Compressing")
        self.assertEqual(raw, "Compressing")
        self.assertEqual(status, "Compressing")
        self.assertNotEqual(status, "Paused")

    def test_session_start_recovers_from_stale_paused_presentation(self):
        """ARTIFICIAL stale presentation: session entry must normalise it."""
        self.enqueue_default()
        self.view.set_paused(True)
        self.assertFalse(self.window.isPaused)
        self.assertTrue(self.view.itemDelegate().paused)

        thread = self.start_compression()
        task = thread.tasks[0]
        self.window.onTaskStarted(task)
        self.app.processEvents()

        self.assertFalse(self.window.isPaused)
        self.assertIs(self.view.itemDelegate().paused, False)
        raw, status = self.rendered_status(task)
        self.assertEqual(raw, "Compressing")
        self.assertEqual(status, "Compressing")

    def test_session_state_writes_only_flow_through_the_seams(self):
        source = (REPO_ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        writers = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "MainWindow":
                for item in node.body:
                    if not isinstance(item, ast.FunctionDef):
                        continue
                    for sub in ast.walk(item):
                        if (isinstance(sub, ast.Attribute)
                                and sub.attr in ("isCompressing", "isPaused")
                                and isinstance(sub.ctx, ast.Store)):
                            writers.setdefault(sub.attr, set()).add(item.name)
        self.assertEqual(
            writers.get("isCompressing"),
            {"__init__", "_set_compression_session_active"},
        )
        self.assertEqual(
            writers.get("isPaused"),
            {"__init__", "_set_session_paused"},
        )


class StartRaisesCompressThread(FakeCompressThread):
    """A worker whose synchronous start() fails, as PySide6 does on an invalid object."""

    def start(self):
        self.start_calls += 1
        raise RuntimeError("simulated start failure")


class WorkerStartFailureRollbackTests(MainWindowQueueTestCase):
    """F.1: a synchronous thread.start() failure must not strand the session."""

    def start_with_failing_thread(self):
        with patch.object(main_window, "CompressThread", StartRaisesCompressThread), \
                patch.object(main_window.QMessageBox, "critical") as critical:
            self.window.startCompress()
        self.app.processEvents()
        return critical

    def assertSessionIdle(self):
        self.assertFalse(self.window.isCompressing)
        self.assertFalse(self.window.isPaused)
        self.assertIs(self.view._queue_locked, False)
        self.assertIs(self.view.itemDelegate().paused, False)

    def assertRolledBackIdle(self):
        """F.1 contract: a failed start also clears the worker reference."""
        self.assertSessionIdle()
        self.assertIsNone(self.window.thread)

    def test_start_failure_rolls_the_session_back(self):
        self.enqueue_default()

        self.start_with_failing_thread()

        self.assertRolledBackIdle()
        self.assertTrue(self.window.startBtn.isEnabled())
        self.assertFalse(self.window.pauseBtn.isEnabled())
        self.assertFalse(self.window.cancelBtn.isEnabled())
        self.assertTrue(self.window.clearBtn.isEnabled())
        self.assertTrue(self.window.dropZone.isEnabled())
        self.assertTrue(self.window.outputEdit.isEnabled())
        self.assertTrue(self.window.browseBtn.isEnabled())
        self.assertTrue(self.window.formatSelector.isEnabled())

    def test_start_failure_leaves_the_queue_usable(self):
        self.enqueue_default()
        self.start_with_failing_thread()

        before = self.model.rowCount()
        self.enqueue(("after_failure.txt",))
        self.assertEqual(self.model.rowCount(), before + 1)

        self.click_delete(0)
        self.assertEqual(self.model.rowCount(), before)

        moved = QSignalSpy(self.model.rowsMoved)
        self.drag(0, self.drop_after(2))
        self.assertEqual(moved.count(), 1)

        self.window.clearTasks()
        self.app.processEvents()
        self.assertEqual(self.model.rowCount(), 0)

    def test_immediate_retry_after_start_failure_succeeds(self):
        self.enqueue_default()
        self.start_with_failing_thread()
        self.assertRolledBackIdle()

        with patch.object(main_window, "CompressThread", FakeCompressThread):
            self.window.startCompress()
        self.app.processEvents()

        thread = self.window.thread
        self.assertTrue(self.window.isCompressing)
        self.assertIs(self.view._queue_locked, True)
        self.assertIsInstance(thread, FakeCompressThread)
        self.assertIs(self.view.itemDelegate().paused, False)
        self.assertFalse(self.window.startBtn.isEnabled())
        self.assertTrue(self.window.pauseBtn.isEnabled())
        self.assertTrue(self.window.cancelBtn.isEnabled())

        with patch.object(main_window, "CompleteDialog"), \
                patch.object(main_window, "WarningArchiveDialog"):
            self.window.onAllFinished(3, 0, 0, str(self.root))
        self.app.processEvents()
        self.assertSessionIdle()

        thread.finished.emit()
        self.app.processEvents()
        self.assertIsNone(self.window.thread)

    def test_start_failure_does_not_fabricate_a_task_result(self):
        tasks = self.enqueue_default()

        self.start_with_failing_thread()

        for task in tasks:
            self.assertNotIn(task.status,
                             ("Completed", "Completed with warnings",
                              "Cancelled", "Failed"))
            self.assertEqual(task.status, "Waiting")
            self.assertEqual(task.error_message, "")
            self.assertEqual(task.progress, 0)

    def test_start_failure_reports_one_startup_error(self):
        self.enqueue_default()

        critical = self.start_with_failing_thread()

        self.assertEqual(critical.call_count, 1)
        message = critical.call_args.args[2]
        self.assertIn("Unable to Start Compression", message)
        self.assertIn("could not be started", message)
        self.assertIn("simulated start failure", message)
        self.assertIn("Try again", message)
        self.assertIn("Compression could not start", self.window.statusLabel.text())

    def test_successful_start_is_unchanged(self):
        self.enqueue_default()

        with patch.object(main_window, "CompressThread", FakeCompressThread), \
                patch.object(main_window.QMessageBox, "critical") as critical:
            self.window.startCompress()
        self.app.processEvents()

        self.assertTrue(self.window.isCompressing)
        self.assertFalse(self.window.isPaused)
        self.assertIs(self.view._queue_locked, True)
        self.assertIsInstance(self.window.thread, FakeCompressThread)
        self.assertEqual(self.window.thread.start_calls, 1)
        self.assertFalse(self.window.startBtn.isEnabled())
        self.assertTrue(self.window.pauseBtn.isEnabled())
        self.assertTrue(self.window.cancelBtn.isEnabled())
        self.assertFalse(self.window.dropZone.isEnabled())
        self.assertEqual(critical.call_count, 0)


class ClearAllPolicyTests(MainWindowQueueTestCase):
    def test_clear_all_empties_the_queue_when_idle(self):
        self.enqueue_default()

        self.window.clearTasks()
        self.app.processEvents()

        self.assertEqual(self.model.rowCount(), 0)
        self.assertEqual(self.window.queueTitle.text(), "Task Queue (0)")

    def test_clear_all_is_blocked_while_compressing(self):
        self.enqueue_default()
        self.start_compression()

        self.window.clearTasks()
        self.app.processEvents()

        self.assertEqual(self.model.rowCount(), 3)
        self.assertTrue(self.window.isCompressing)


class EmptyStateIntegrationTests(MainWindowQueueTestCase):
    def test_empty_state_is_parented_to_the_view_viewport(self):
        self.assertIs(self.window.emptyState.parent(), self.view.viewport())

    def test_empty_state_tracks_model_rows(self):
        self.assertTrue(self.window.emptyState.isVisible())

        self.enqueue_default()
        self._wait_for_empty_fade()
        self.assertFalse(self.window.emptyState.isVisible())

        self.window.clearTasks()
        self._wait_for_empty_fade()
        self.assertTrue(self.window.emptyState.isVisible())

    def _wait_for_empty_fade(self):
        for _ in range(50):
            QTest.qWait(10)
            self.app.processEvents()

    def test_empty_state_keeps_its_opacity_animation(self):
        self.assertTrue(hasattr(self.window, "_emptyFade"))
        self.assertGreater(self.window._emptyFade.duration(), 0)


class ListGridIntegrationTests(MainWindowQueueTestCase):
    def test_set_queue_view_switches_grid_mode(self):
        self.enqueue_default()

        self.window.setQueueView(True)
        self.app.processEvents()
        self.assertTrue(self.view._grid)
        self.assertTrue(self.window.gridView)

        self.window.setQueueView(False)
        self.app.processEvents()
        self.assertFalse(self.view._grid)
        self.assertFalse(self.window.gridView)

    def test_list_grid_switch_keeps_order_identity_and_model(self):
        tasks = self.enqueue_default()
        reset = QSignalSpy(self.model.modelReset)
        ids_before = self.task_ids(self.model.ordered_tasks())

        for grid in (True, False, True):
            self.window.setQueueView(grid)
            self.app.processEvents()
            self.assertEqual(self.task_ids(self.model.ordered_tasks()), ids_before)
            self.assertEqual(self.model.ordered_tasks(), tuple(tasks))

        self.assertEqual(reset.count(), 0)
        self.assertIs(self.view.model(), self.model)


class NoPerRowWidgetTests(MainWindowQueueTestCase):
    def test_runtime_updates_do_not_create_per_row_widgets(self):
        self.enqueue_default()
        order_before = self.task_ids(self.model.ordered_tasks())
        widget_count = len(QApplication.allWidgets())
        viewport_widgets = self.queueWidgetCount()

        with patch.object(QAbstractItemView, "setIndexWidget",
                          side_effect=AssertionError("setIndexWidget used")):
            task = self.model.task_at(0)
            self.window.onTaskStarted(task)
            self.window.onTaskProgress(task, 30)
            self.window.onTaskFinished(task, "Completed")
            self.window.setCompressionControls(True)
            self.window.setCompressionControls(False)
            self.window.updateDensity()

        self.assertEqual(task.status, "Completed")
        self.assertEqual(task.progress, 100)
        self.assertEqual(self.task_ids(self.model.ordered_tasks()), order_before)
        self.assertNoPerRowWidgets()
        self.assertEqual(self.queueWidgetCount(), viewport_widgets)
        self.assertEqual(len(QApplication.allWidgets()), widget_count)

    def test_production_does_not_use_item_widgets(self):
        self.enqueue_default()
        self.assertEqual(self.window.findChildren(QListWidget), [])
        self.assertNoPerRowWidgets()
        baseline = self.queueWidgetCount()

        self.enqueue(("extra1.txt", "extra2.txt", "extra3.txt"))

        self.assertNoPerRowWidgets()
        self.assertEqual(self.queueWidgetCount(), baseline)


if __name__ == "__main__":
    unittest.main()
