import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QPainter, QPixmap, QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QListView, QStyleOptionViewItem, QWidget
from qfluentwidgets import FluentIcon, Theme, setTheme

from core.task import Task
from ui.task_delegate import TaskQueueDelegate
from ui.task_model import TaskQueueModel
from ui.task_queue_controller import TaskQueueController
from ui.task_queue_view import TaskQueueView


class TaskQueueDelegateViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.model = TaskQueueModel()
        self.view = TaskQueueView(self.model)
        self.view.resize(900, 350)
        self.view.show()
        self.app.processEvents()

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        self.app.processEvents()

    def assertNoEmbeddedRowWidgets(self):
        """The queue must render through the delegate: no per-row QWidget for any row."""
        for row in range(self.model.rowCount()):
            self.assertIsNone(self.view.indexWidget(self.model.index(row)), row)
        self.assertEqual(self.view.viewport().findChildren(QWidget), [])

    def fill(self, count):
        self.model.append_tasks(Task(f"C:/测试/{i:03}.txt") for i in range(count))
        self.app.processEvents()

    def drag_to(self, source_row, point):
        source = self.view.visualRect(self.model.index(source_row)).center()
        viewport = self.view.viewport()
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=source)
        QTest.mouseMove(viewport, point)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=point)

    def drop_point(self, row, before=True):
        rect = self.view.visualRect(self.model.index(row))
        if self.view._grid:
            return QPoint(rect.left() + rect.width() * (1 if before else 3) // 4,
                          rect.center().y())
        return QPoint(rect.center().x(),
                      rect.top() + rect.height() * (1 if before else 3) // 4)

    def test_architecture_and_counts(self):
        self.assertIsInstance(self.view, QListView)
        self.assertIs(self.view.model(), self.model)
        self.assertIsInstance(self.view.itemDelegate(), TaskQueueDelegate)
        self.assertEqual(self.view.verticalScrollMode(), QListView.ScrollMode.ScrollPerPixel)
        for count in (0, 1, 10, 52, 100):
            self.model.clear()
            self.fill(count)
            self.view.viewport().grab()
            self.assertEqual(self.model.rowCount(), count)
            self.assertNoEmbeddedRowWidgets()
            for row in range(count):
                self.assertIsNone(self.view.indexWidget(self.model.index(row)))

    def test_list_grid_order_and_mapping(self):
        self.fill(52)
        expected = self.model.ordered_tasks()
        for columns in (2, 3, 4):
            self.view.resize(432 * columns + 16, 350)
            self.view.set_grid_mode(True)
            self.app.processEvents()
            rects = [self.view.visualRect(self.model.index(row)) for row in range(columns + 1)]
            self.assertTrue(all(rects[i].top() == rects[0].top() for i in range(columns)))
            self.assertTrue(all(rects[i].left() < rects[i + 1].left() for i in range(columns - 1)))
            self.assertGreater(rects[columns].top(), rects[0].top())
            self.assertEqual(rects[columns].left(), rects[0].left())
            self.assertLessEqual(rects[columns - 1].right(), self.view.viewport().width())
            self.assertEqual(self.model.ordered_tasks(), expected)
        self.view.set_grid_mode(False)
        self.app.processEvents()
        self.assertEqual(self.model.ordered_tasks(), expected)
        self.assertEqual(self.view.visualRect(self.model.index(1)).left(),
                         self.view.visualRect(self.model.index(0)).left())
        self.assertEqual(self.view.horizontalScrollBar().maximum(), 0)

    def test_scrolling_does_not_reflow_or_create_cards(self):
        self.fill(100)
        self.view.set_grid_mode(True)
        self.app.processEvents()
        resets = []
        self.model.modelReset.connect(lambda: resets.append(True))
        before = self.view.gridSize()
        option = QStyleOptionViewItem()
        hint = self.view.itemDelegate().sizeHint(option, self.model.index(0))
        widget_count = len(QApplication.allWidgets())
        bar = self.view.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        with patch.object(self.view, "setGridSize", wraps=self.view.setGridSize) as grid_changes:
            for value in range(0, bar.maximum(), max(1, bar.maximum() // 20)):
                bar.setValue(value)
                self.app.processEvents()
            self.assertEqual(grid_changes.call_count, 0)
        self.assertEqual(self.view.gridSize(), before)
        self.assertEqual(self.view.itemDelegate().sizeHint(option, self.model.index(0)), hint)
        self.assertEqual(resets, [])
        self.assertEqual(len(QApplication.allWidgets()), widget_count)
        self.assertNoEmbeddedRowWidgets()

    def test_active_wheel_timer_is_not_restarted(self):
        self.fill(100)
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        timer = self.view._wheel_timer

        def wheel(angle):
            event = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(),
                                QPoint(0, angle), Qt.NoButton, Qt.NoModifier,
                                Qt.ScrollUpdate, False)
            self.view.wheelEvent(event)

        with patch.object(timer, "start", wraps=timer.start) as starts:
            wheel(-120)
            self.assertEqual(starts.call_count, 1)
            self.assertTrue(timer.isActive())
            first_target = self.view._wheel_target
            self.assertGreater(first_target, bar.value())

            for _ in range(3):
                previous_target = self.view._wheel_target
                wheel(-120)
                self.assertGreater(self.view._wheel_target, previous_target)
                self.assertTrue(timer.isActive())
                self.assertEqual(starts.call_count, 1)

            previous_target = self.view._wheel_target
            wheel(120)
            self.assertLess(self.view._wheel_target, previous_target)
            self.assertTrue(timer.isActive())
            self.assertEqual(starts.call_count, 1)

            timer.stop()
            self.assertFalse(timer.isActive())
            wheel(-120)
            self.assertEqual(starts.call_count, 2)
            self.assertTrue(timer.isActive())

    def test_pixel_delta_keeps_direct_scroll_path(self):
        self.fill(100)
        bar = self.view.verticalScrollBar()
        timer = self.view._wheel_timer
        with patch.object(timer, "start", wraps=timer.start) as starts:
            angle = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(),
                                QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
                                Qt.ScrollUpdate, False)
            self.view.wheelEvent(angle)
            self.assertTrue(timer.isActive())
            before = bar.value()
            pixel = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, -30),
                                QPoint(), Qt.NoButton, Qt.NoModifier,
                                Qt.ScrollUpdate, False)
            self.view.wheelEvent(pixel)
            self.assertEqual(bar.value(), before + 30)
            self.assertFalse(timer.isActive())
            self.assertEqual(starts.call_count, 1)

    def test_list_delete_click_removes_only_clicked_task(self):
        tasks = [Task(f"C:/queue/{name}.txt") for name in "ABC"]
        self.model.append_tasks(tasks)
        self.app.processEvents()
        removed = QSignalSpy(self.model.rowsRemoved)
        reset = QSignalSpy(self.model.modelReset)
        rect = self.view.visualRect(self.model.index(1))
        point = QPoint(rect.right() - 28, rect.center().y())

        QTest.mouseClick(self.view.viewport(), Qt.MouseButton.LeftButton, pos=point)

        self.assertEqual(self.model.ordered_tasks(), (tasks[0], tasks[2]))
        self.assertEqual(removed.count(), 1)
        self.assertEqual([removed.at(0)[1], removed.at(0)[2]], [1, 1])
        self.assertEqual(reset.count(), 0)

    def test_delete_requires_press_and_release_on_same_affordance(self):
        tasks = [Task(f"C:/queue/{name}.txt") for name in "ABC"]
        self.model.append_tasks(tasks)
        self.app.processEvents()
        rect = self.view.visualRect(self.model.index(1))
        delete = QPoint(rect.right() - 28, rect.center().y())
        outside = rect.center()
        viewport = self.view.viewport()

        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=outside)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=delete)
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=delete)
        QTest.mouseMove(viewport, outside)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=outside)

        self.assertEqual(self.model.ordered_tasks(), tuple(tasks))
        QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=delete)
        self.assertEqual(self.model.ordered_tasks(), (tasks[0], tasks[2]))

    def test_non_deletable_task_ignores_delete_click(self):
        tasks = [Task("C:/ready.txt"), Task("C:/active.txt", status="Compressing"),
                 Task("C:/later.txt")]
        self.model.append_tasks(tasks)
        self.app.processEvents()
        index = self.model.index(1)
        self.assertFalse(self.model.data(index, TaskQueueModel.DeletableRole))
        rect = self.view.visualRect(index)
        point = QPoint(rect.right() - 28, rect.center().y())
        removed = QSignalSpy(self.model.rowsRemoved)

        QTest.mouseClick(self.view.viewport(), Qt.MouseButton.LeftButton, pos=point)

        self.assertEqual(self.model.ordered_tasks(), tuple(tasks))
        self.assertEqual(removed.count(), 0)

    def test_delete_uses_current_task_identity_after_move(self):
        tasks = [Task(f"C:/queue/{name}.txt") for name in "ABCD"]
        self.model.append_tasks(tasks)
        self.assertTrue(self.model.moveRows(QModelIndex(), 1, 1, QModelIndex(), 4))
        self.app.processEvents()
        index = self.model.index(3)
        self.assertIs(self.model.data(index, TaskQueueModel.TaskRole), tasks[1])
        rect = self.view.visualRect(index)
        point = QPoint(rect.right() - 28, rect.center().y())

        QTest.mouseClick(self.view.viewport(), Qt.MouseButton.LeftButton, pos=point)

        self.assertEqual(self.model.ordered_tasks(), (tasks[0], tasks[2], tasks[3]))
        self.assertEqual(self.model.row_for_task(tasks[1]), -1)

    def test_grid_delete_closes_gap_without_reset(self):
        for columns in (2, 3, 4):
            with self.subTest(columns=columns):
                self.model.clear()
                tasks = [Task(f"C:/queue/{i:02}.txt") for i in range(12)]
                self.model.append_tasks(tasks)
                self.view.resize(432 * columns + 16, 350)
                self.view.set_grid_mode(True)
                self.app.processEvents()
                index = self.model.index(columns)
                before = self.view.visualRect(index)
                point = QPoint(before.right() - 28, before.center().y())
                removed = QSignalSpy(self.model.rowsRemoved)
                reset = QSignalSpy(self.model.modelReset)

                QTest.mouseClick(self.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
                self.app.processEvents()
                self.view.viewport().grab()

                self.assertEqual(self.model.ordered_tasks(),
                                 tuple(task for task in tasks if task is not tasks[columns]))
                self.assertIs(self.model.data(self.model.index(columns), TaskQueueModel.TaskRole),
                              tasks[columns + 1])
                self.assertEqual(self.view.visualRect(self.model.index(columns)), before)
                self.assertEqual(removed.count(), 1)
                self.assertEqual(reset.count(), 0)
                self.assertNoEmbeddedRowWidgets()

    def test_delete_across_compact_threshold_updates_existing_cell_height(self):
        for grid, expected_height in ((False, 66), (True, 68)):
            with self.subTest(grid=grid):
                self.model.clear()
                self.model.append_tasks(Task(f"C:/queue/{i}.txt") for i in range(5))
                self.view.set_grid_mode(grid)
                self.app.processEvents()
                rect = self.view.visualRect(self.model.index(4))
                point = QPoint(rect.right() - 28, rect.center().y())

                QTest.mouseClick(self.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
                self.app.processEvents()

                self.assertEqual(self.model.rowCount(), 4)
                self.assertEqual(self.view.gridSize().height(), expected_height)

    def test_list_drag_moves_first_task_before_middle_task(self):
        tasks = [Task(f"C:/queue/{name}.txt") for name in "ABCDE"]
        self.model.append_tasks(tasks)
        self.app.processEvents()
        source = self.view.visualRect(self.model.index(0)).center()
        target = self.view.visualRect(self.model.index(2))
        destination = QPoint(target.center().x(), target.top() + target.height() // 4)
        moved = QSignalSpy(self.model.rowsMoved)
        reset = QSignalSpy(self.model.modelReset)

        QTest.mousePress(self.view.viewport(), Qt.MouseButton.LeftButton, pos=source)
        QTest.mouseMove(self.view.viewport(), destination)
        QTest.mouseRelease(self.view.viewport(), Qt.MouseButton.LeftButton, pos=destination)

        self.assertEqual(self.model.ordered_tasks(),
                         (tasks[1], tasks[0], tasks[2], tasks[3], tasks[4]))
        self.assertEqual(moved.count(), 1)
        self.assertEqual(reset.count(), 0)

    def test_list_drag_move_positions_use_qt_destination_semantics(self):
        cases = (
            (0, 4, False, "BCDEA"),
            (2, 0, True, "CABDE"),
            (2, 4, False, "ABDEC"),
            (4, 0, True, "EABCD"),
            (4, 2, True, "ABECD"),
            (1, 2, False, "ACBDE"),
            (2, 1, True, "ACBDE"),
        )
        for source, target, before, expected in cases:
            with self.subTest(source=source, target=target, before=before):
                self.model.clear()
                tasks = [Task(f"C:/queue/{name}.txt") for name in "ABCDE"]
                self.model.append_tasks(tasks)
                self.view.set_grid_mode(False)
                self.app.processEvents()
                moving = QSignalSpy(self.model.rowsAboutToBeMoved)
                moved = QSignalSpy(self.model.rowsMoved)
                reset = QSignalSpy(self.model.modelReset)

                self.drag_to(source, self.drop_point(target, before))

                by_name = {task.name[0]: task for task in tasks}
                self.assertEqual(self.model.ordered_tasks(),
                                 tuple(by_name[name] for name in expected))
                self.assertEqual(moving.count(), 1)
                self.assertEqual(moved.count(), 1)
                self.assertEqual(reset.count(), 0)
                self.assertEqual({id(task) for task in self.model.ordered_tasks()},
                                 {id(task) for task in tasks})

    def test_drag_no_op_and_small_motion_leave_order_unchanged(self):
        tasks = [Task(f"C:/queue/{name}.txt") for name in "ABCDE"]
        self.model.append_tasks(tasks)
        self.app.processEvents()
        moved = QSignalSpy(self.model.rowsMoved)
        reset = QSignalSpy(self.model.modelReset)

        self.drag_to(2, self.drop_point(2, True))
        self.drag_to(2, self.drop_point(2, False))
        self.drag_to(2, self.drop_point(3, True))
        source = self.view.visualRect(self.model.index(1)).center()
        viewport = self.view.viewport()
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=source)
        QTest.mouseMove(viewport, source + QPoint(1, 1))
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=source + QPoint(1, 1))

        self.assertEqual(self.model.ordered_tasks(), tuple(tasks))
        self.assertEqual(moved.count(), 0)
        self.assertEqual(reset.count(), 0)

    def test_list_drop_in_empty_space_after_last_item_moves_to_end(self):
        tasks = [Task(f"C:/queue/{name}.txt") for name in "ABCDE"]
        self.model.append_tasks(tasks)
        self.app.processEvents()
        last = self.view.visualRect(self.model.index(4))
        empty = QPoint(last.center().x(), last.bottom() + 12)

        self.drag_to(0, empty)

        self.assertEqual(self.model.ordered_tasks(),
                         (tasks[1], tasks[2], tasks[3], tasks[4], tasks[0]))

    def test_grid_drag_across_rows_keeps_linear_order(self):
        for columns in (2, 3, 4):
            with self.subTest(columns=columns):
                self.model.clear()
                tasks = [Task(f"C:/queue/{i:02}.txt") for i in range(12)]
                self.model.append_tasks(tasks)
                self.view.resize(432 * columns + 16, 350)
                self.view.set_grid_mode(True)
                self.app.processEvents()
                target = columns + 1
                moving = QSignalSpy(self.model.rowsAboutToBeMoved)
                moved = QSignalSpy(self.model.rowsMoved)
                reset = QSignalSpy(self.model.modelReset)

                self.drag_to(0, self.drop_point(target, True))
                self.app.processEvents()

                expected = tuple(tasks[1:target] + [tasks[0]] + tasks[target:])
                self.assertEqual(self.model.ordered_tasks(), expected)
                self.assertEqual(moving.count(), 1)
                self.assertEqual(moved.count(), 1)
                self.assertEqual(reset.count(), 0)
                self.assertNoEmbeddedRowWidgets()

    def test_grid_drop_in_empty_space_after_last_item_moves_to_end(self):
        for columns in (2, 3, 4):
            with self.subTest(columns=columns):
                self.model.clear()
                tasks = [Task(f"C:/queue/{i:02}.txt") for i in range(11)]
                self.model.append_tasks(tasks)
                self.view.resize(432 * columns + 16, 500)
                self.view.set_grid_mode(True)
                self.app.processEvents()
                last = self.view.visualRect(self.model.index(10))
                empty = QPoint(last.right() + 12, last.center().y())

                self.drag_to(0, empty)

                self.assertEqual(self.model.ordered_tasks(), tuple(tasks[1:] + tasks[:1]))

    def test_drag_order_survives_list_grid_switches_and_delete(self):
        tasks = [Task(f"C:/queue/{name}.txt") for name in "ABCDE"]
        self.model.append_tasks(tasks)
        self.app.processEvents()
        self.drag_to(4, self.drop_point(1, True))
        expected = (tasks[0], tasks[4], tasks[1], tasks[2], tasks[3])
        self.assertEqual(self.model.ordered_tasks(), expected)

        self.view.resize(900, 350)
        self.view.set_grid_mode(True)
        self.app.processEvents()
        self.assertEqual(self.model.ordered_tasks(), expected)
        self.drag_to(3, self.drop_point(0, True))
        expected = (tasks[2], tasks[0], tasks[4], tasks[1], tasks[3])
        self.assertEqual(self.model.ordered_tasks(), expected)

        self.view.set_grid_mode(False)
        self.app.processEvents()
        self.assertEqual(self.model.ordered_tasks(), expected)
        self.view.viewport().grab()
        rect = self.view.visualRect(self.model.index(2))
        delete = QPoint(rect.right() - 28, rect.center().y())
        QTest.mouseClick(self.view.viewport(), Qt.MouseButton.LeftButton, pos=delete)
        self.assertEqual(self.model.ordered_tasks(),
                         (tasks[2], tasks[0], tasks[1], tasks[3]))
        self.assertEqual(self.model.row_for_task(tasks[4]), -1)

    def test_drag_from_delete_affordance_does_not_move_or_delete(self):
        tasks = [Task(f"C:/queue/{name}.txt") for name in "ABCDE"]
        self.model.append_tasks(tasks)
        self.app.processEvents()
        rect = self.view.visualRect(self.model.index(1))
        delete = QPoint(rect.right() - 28, rect.center().y())
        destination = self.drop_point(3, False)
        moved = QSignalSpy(self.model.rowsMoved)
        removed = QSignalSpy(self.model.rowsRemoved)
        viewport = self.view.viewport()

        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=delete)
        QTest.mouseMove(viewport, destination)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=destination)

        self.assertEqual(self.model.ordered_tasks(), tuple(tasks))
        self.assertEqual(moved.count(), 0)
        self.assertEqual(removed.count(), 0)

    def test_text_status_and_progress_paint(self):
        tasks = [Task("C:/中文/" + "很长的文件名" * 20 + ".txt", status=status, progress=43)
                 for status in ("Waiting", "Compressing", "Completed", "Completed with warnings", "Failed", "Cancelled")]
        self.model.append_tasks(tasks)
        self.view.viewport().grab()
        self.view.itemDelegate().paused = True
        self.view.viewport().grab()
        self.assertEqual(self.model.data(self.model.index(1), TaskQueueModel.StatusRole), "Compressing")
        self.assertEqual(self.model.data(self.model.index(1), TaskQueueModel.ProgressRole), 43)
        self.assertIn("中文", self.model.data(self.model.index(0), TaskQueueModel.PathRole))

    def test_light_and_dark_paint(self):
        self.fill(10)
        try:
            for theme in (Theme.LIGHT, Theme.DARK):
                setTheme(theme)
                self.app.processEvents()
                image = self.view.viewport().grab().toImage()
                self.assertFalse(image.isNull())
        finally:
            setTheme(Theme.AUTO)

    def test_repeated_paint_reuses_icon_and_folder_result(self):
        self.fill(100)
        self.view.set_grid_mode(True)
        self.view.viewport().repaint()
        icon_calls = []
        folder_queries = []
        original_icon = FluentIcon.icon
        original_is_dir = Path.is_dir

        def icon(icon, *args, **kwargs):
            if icon is FluentIcon.DELETE:
                icon_calls.append(True)
            return original_icon(icon, *args, **kwargs)

        def is_dir(path, *args, **kwargs):
            folder_queries.append(True)
            return original_is_dir(path, *args, **kwargs)

        with patch.object(FluentIcon, "icon", icon), patch.object(Path, "is_dir", is_dir):
            for _ in range(3):
                self.view.viewport().repaint()
            self.view.verticalScrollBar().setValue(120)
            self.app.processEvents()
        self.assertEqual(icon_calls, [])
        self.assertEqual(folder_queries, [])

    def test_delete_icon_cache_survives_theme_and_dpr_changes(self):
        self.fill(1)
        delegate = self.view.itemDelegate()
        original_icon = FluentIcon.icon
        calls = []

        def icon(value, *args, **kwargs):
            if value is FluentIcon.DELETE:
                calls.append(True)
            return original_icon(value, *args, **kwargs)

        try:
            setTheme(Theme.LIGHT)
            self.view.viewport().repaint()
            with patch.object(FluentIcon, "icon", icon):
                setTheme(Theme.DARK)
                self.view.viewport().repaint()
                self.assertEqual(len(calls), 1)
                setTheme(Theme.LIGHT)
                self.view.viewport().repaint()
                self.assertEqual(len(calls), 1)

                pixmap = QPixmap(800, 120)
                pixmap.setDevicePixelRatio(2.0)
                option = QStyleOptionViewItem()
                option.rect = QRect(0, 0, 400, 60)
                for _ in range(2):
                    painter = QPainter(pixmap)
                    delegate.paint(painter, option, self.model.index(0))
                    painter.end()
                self.assertEqual(len(calls), 2)
        finally:
            setTheme(Theme.AUTO)

    def test_card_chrome_cache_tracks_geometry_theme_and_dpr(self):
        self.fill(1)
        delegate = self.view.itemDelegate()
        delegate._card_chrome.clear()
        image = QPixmap(800, 120)
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 400, 60)

        def paint():
            painter = QPainter(image)
            delegate.paint(painter, option, self.model.index(0))
            painter.end()

        try:
            setTheme(Theme.LIGHT)
            paint()
            first = next(reversed(delegate._card_chrome.values()))
            paint()
            self.assertIs(next(reversed(delegate._card_chrome.values())), first)
            option.rect.setWidth(420)
            paint()
            self.assertEqual(len(delegate._card_chrome), 2)
            setTheme(Theme.DARK)
            paint()
            self.assertEqual(len(delegate._card_chrome), 3)
            image.setDevicePixelRatio(2.0)
            paint()
            self.assertEqual(len(delegate._card_chrome), 4)
            for width in range(421, 450):
                option.rect.setWidth(width)
                paint()
            self.assertEqual(len(delegate._card_chrome), 24)
        finally:
            setTheme(Theme.AUTO)

    def test_full_card_cache_tracks_visual_fingerprint(self):
        task = Task("C:/中文/很长的文件名" * 8 + ".txt")
        self.model.append_task(task)
        delegate = self.view.itemDelegate()
        delegate._full_cards.clear()
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 400, 60)

        def paint(dpr=1.0):
            surface = QPixmap(round(420 * dpr), round(80 * dpr))
            surface.setDevicePixelRatio(dpr)
            surface.fill(Qt.GlobalColor.white)
            painter = QPainter(surface)
            delegate.paint(painter, option, self.model.index(0))
            painter.end()
            return surface.toImage()

        try:
            setTheme(Theme.LIGHT)
            first = paint()
            cached = next(reversed(delegate._full_cards.values()))
            self.assertEqual(paint(), first)
            self.assertIs(next(reversed(delegate._full_cards.values())), cached)
            self.assertEqual(len(delegate._full_cards), 1)
            option.rect.setWidth(420)
            paint()
            self.assertEqual(len(delegate._full_cards), 2)
            setTheme(Theme.DARK)
            paint()
            self.assertEqual(len(delegate._full_cards), 3)
            setTheme(Theme.LIGHT)
            paint(2.0)
            self.assertEqual(len(delegate._full_cards), 4)
            high_dpi_card = next(reversed(delegate._full_cards.values()))
            self.assertEqual(high_dpi_card.devicePixelRatioF(), 2.0)
            self.assertEqual(high_dpi_card.size().width(), 2 * (option.rect.width() + 2))
            before_status = paint(2.0)
            task.status = "Completed"
            self.model.notify_task_changed(task, [TaskQueueModel.StatusRole])
            self.assertNotEqual(before_status, paint(2.0))
            self.assertEqual(len(delegate._full_cards), 5)
            task.path = "C:/中文/另一个文件名.txt"
            self.model.notify_task_changed(task, [TaskQueueModel.PathRole])
            paint(2.0)
            self.assertEqual(len(delegate._full_cards), 6)
            with patch.object(Path, "is_dir", return_value=True):
                self.model.notify_task_changed(task, [TaskQueueModel.IsFolderRole])
            paint(2.0)
            self.assertEqual(len(delegate._full_cards), 7)
        finally:
            setTheme(Theme.AUTO)

    def test_dynamic_progress_bypasses_full_card_cache_and_move_reuses_it(self):
        static = Task("C:/static.txt")
        active = Task("C:/active.txt", status="Compressing", progress=10)
        self.model.append_tasks([static, active])
        delegate = self.view.itemDelegate()
        delegate._full_cards.clear()
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 400, 60)

        def paint(row):
            surface = QPixmap(420, 80)
            surface.fill(Qt.GlobalColor.white)
            painter = QPainter(surface)
            delegate.paint(painter, option, self.model.index(row))
            painter.end()
            return surface.toImage()

        before = paint(1)
        active.progress = 75
        self.model.notify_task_changed(active, [TaskQueueModel.ProgressRole])
        self.assertNotEqual(before, paint(1))
        self.assertEqual(len(delegate._full_cards), 0)
        paint(0)
        hits = delegate._full_card_hits
        self.assertTrue(self.model.moveRows(self.model.index(-1), 0, 1,
                                             self.model.index(-1), 2))
        paint(1)
        self.assertEqual(delegate._full_card_hits, hits + 1)
        self.assertTrue(self.model.remove_task(static))
        self.assertEqual(self.model.row_for_task(static), -1)
        paint(0)
        self.assertEqual(len(delegate._full_cards), 1)
        replacement = Task("C:/static.txt")
        self.model.append_task(replacement)
        misses = delegate._full_card_misses
        paint(1)
        self.assertEqual(delegate._full_card_misses, misses + 1)
        self.assertNoEmbeddedRowWidgets()

    def test_full_card_cache_is_bounded_without_filesystem_paint_queries(self):
        self.fill(140)
        delegate = self.view.itemDelegate()
        delegate._full_cards.clear()
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 400, 60)
        surface = QPixmap(420, 80)
        with patch.object(Path, "is_dir", side_effect=AssertionError("paint queried filesystem")):
            for row in range(140):
                painter = QPainter(surface)
                delegate.paint(painter, option, self.model.index(row))
                painter.end()
        self.assertEqual(len(delegate._full_cards), 96)
        self.assertGreaterEqual(delegate._full_card_evictions, 44)

    def test_pause_and_resume_change_presentation_only(self):
        tasks = [Task(f"C:/queue/{name}.txt") for name in "ABC"]
        tasks[1].status = "Compressing"
        self.model.append_tasks(tasks)
        self.app.processEvents()
        delegate = self.view.itemDelegate()
        delegate.paused = False
        changed = QSignalSpy(self.model.dataChanged)
        reset = QSignalSpy(self.model.modelReset)
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 400, 60)

        def paint(row):
            surface = QPixmap(420, 80)
            surface.fill(Qt.GlobalColor.white)
            painter = QPainter(surface)
            delegate.paint(painter, option, self.model.index(row))
            painter.end()
            return surface.toImage()

        running = paint(1)
        viewport = self.view.viewport()
        with patch.object(viewport, "update", wraps=viewport.update) as repaints:
            self.view.set_paused(True)
        self.assertEqual(repaints.call_count, 1)
        self.assertNotEqual(paint(1), running)

        self.assertEqual(tasks[1].status, "Compressing")
        self.assertEqual(
            self.model.data(self.model.index(1), TaskQueueModel.StatusRole),
            "Compressing",
        )
        self.assertEqual(
            self.model.data(self.model.index(1), TaskQueueModel.DisplayStatusRole),
            "Compressing",
        )
        self.assertFalse(
            self.model.data(self.model.index(1), TaskQueueModel.DeletableRole)
        )
        self.assertEqual(changed.count(), 0)
        self.assertEqual(reset.count(), 0)
        self.assertEqual(self.model.ordered_tasks(), tuple(tasks))
        self.assertEqual(
            [id(task) for task in self.model.ordered_tasks()],
            [id(task) for task in tasks],
        )

        with patch.object(viewport, "update", wraps=viewport.update) as repaints:
            self.view.set_paused(False)
        self.assertEqual(repaints.call_count, 1)
        self.assertEqual(paint(1), running)
        self.assertEqual(tasks[1].status, "Compressing")
        self.assertFalse(
            self.model.data(self.model.index(1), TaskQueueModel.DeletableRole)
        )
        self.assertEqual(changed.count(), 0)
        self.assertEqual(reset.count(), 0)

    def test_pause_repaints_only_when_value_changes(self):
        self.fill(3)
        viewport = self.view.viewport()
        with patch.object(viewport, "update", wraps=viewport.update) as repaints:
            self.view.set_paused(False)
            self.view.set_paused(False)
        self.assertEqual(repaints.call_count, 0)

    def test_controller_forwards_pause_to_view(self):
        tasks = [Task("C:/one.txt", status="Compressing")]
        self.model.append_tasks(tasks)
        controller = TaskQueueController(self.model, self.view)

        controller.set_paused(True)
        self.assertTrue(self.view.itemDelegate().paused)
        controller.set_paused(False)
        self.assertFalse(self.view.itemDelegate().paused)
        self.assertEqual(tasks[0].status, "Compressing")

    def test_state_updates_do_not_reflow_or_rebuild_cards(self):
        tasks = [Task(f"C:/queue/{i:02}.txt") for i in range(12)]
        tasks[3].status = "Compressing"
        self.model.append_tasks(tasks)
        self.view.resize(432 * 2 + 16, 350)
        self.view.set_grid_mode(True)
        self.app.processEvents()
        controller = TaskQueueController(self.model, self.view)
        before_grid = self.view.gridSize()
        widget_count = len(QApplication.allWidgets())

        with patch.object(self.view, "setGridSize",
                          wraps=self.view.setGridSize) as grid_changes, \
                patch.object(self.view, "doItemsLayout",
                             wraps=self.view.doItemsLayout) as layouts:
            controller.on_task_started(tasks[5])
            controller.on_task_progress(tasks[3], 37)
            controller.on_task_finished(tasks[3], "Completed")

        self.assertEqual(grid_changes.call_count, 0)
        self.assertEqual(layouts.call_count, 0)
        self.assertEqual(self.view.gridSize(), before_grid)
        self.assertNoEmbeddedRowWidgets()
        self.assertEqual(len(QApplication.allWidgets()), widget_count)

    def test_delete_after_state_update_removes_correct_identity(self):
        tasks = [Task(f"C:/queue/{name}.txt") for name in "ABCDE"]
        self.model.append_tasks(tasks)
        self.app.processEvents()
        controller = TaskQueueController(self.model, self.view)
        controller.on_task_finished(tasks[2], "Completed")
        self.app.processEvents()

        rect = self.view.visualRect(self.model.index(2))
        delete = QPoint(rect.right() - 28, rect.center().y())
        QTest.mouseClick(self.view.viewport(), Qt.MouseButton.LeftButton, pos=delete)

        self.assertEqual(self.model.row_for_task(tasks[2]), -1)
        self.assertEqual(
            self.model.ordered_tasks(),
            (tasks[0], tasks[1], tasks[3], tasks[4]),
        )

    def test_compressing_and_paused_rows_are_not_deletable(self):
        tasks = [Task("C:/queue/one.txt", status="Compressing"),
                 Task("C:/queue/two.txt")]
        self.model.append_tasks(tasks)
        self.app.processEvents()
        controller = TaskQueueController(self.model, self.view)
        controller.set_paused(True)
        self.app.processEvents()

        self.assertFalse(
            self.model.data(self.model.index(0), TaskQueueModel.DeletableRole)
        )
        removed = QSignalSpy(self.model.rowsRemoved)
        rect = self.view.visualRect(self.model.index(0))
        delete = QPoint(rect.right() - 28, rect.center().y())
        QTest.mouseClick(self.view.viewport(), Qt.MouseButton.LeftButton, pos=delete)

        self.assertEqual(removed.count(), 0)
        self.assertEqual(self.model.ordered_tasks(), tuple(tasks))

        controller.set_paused(False)
        self.assertFalse(
            self.model.data(self.model.index(0), TaskQueueModel.DeletableRole)
        )
        self.assertEqual(tasks[0].status, "Compressing")

    def test_list_grid_switch_preserves_state_progress_identity_and_order(self):
        tasks = [Task(f"C:/queue/{name}.txt") for name in "ABCDE"]
        tasks[1].status = "Compressing"
        tasks[1].progress = 42
        tasks[3].status = "Completed with warnings"
        self.model.append_tasks(tasks)
        self.view.resize(432 * 2 + 16, 350)
        controller = TaskQueueController(self.model, self.view)
        controller.set_paused(True)
        self.app.processEvents()
        reset = QSignalSpy(self.model.modelReset)
        snapshot = tuple(
            (task.status, task.progress) for task in self.model.ordered_tasks()
        )
        identity = [id(task) for task in self.model.ordered_tasks()]

        for grid in (True, False, True):
            self.view.set_grid_mode(grid)
            self.app.processEvents()
            self.assertEqual(
                tuple(
                    (task.status, task.progress)
                    for task in self.model.ordered_tasks()
                ),
                snapshot,
            )
            self.assertEqual(
                [id(task) for task in self.model.ordered_tasks()], identity
            )
            self.assertEqual(
                self.model.data(self.model.index(1), TaskQueueModel.StatusRole),
                "Compressing",
            )
            self.assertEqual(
                self.model.data(self.model.index(1), TaskQueueModel.ProgressRole),
                42,
            )
            self.assertEqual(
                self.model.data(
                    self.model.index(3), TaskQueueModel.DisplayStatusRole
                ),
                "Warning",
            )

        self.assertTrue(self.view.itemDelegate().paused)
        self.assertEqual(reset.count(), 0)


if __name__ == "__main__":
    unittest.main()
