import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtTest import QSignalSpy

from core.task import Task
from ui.task_model import TaskQueueModel
from ui.task_queue_controller import TaskQueueController


class TaskQueueModelTests(unittest.TestCase):
    def setUp(self):
        self.model = TaskQueueModel()

    def test_empty_model(self):
        self.assertEqual(self.model.rowCount(), 0)
        self.assertEqual(self.model.ordered_tasks(), ())

    def test_append_preserves_order_and_task_identity(self):
        tasks = [Task("c.txt"), Task("a.txt"), Task("b.txt")]
        inserted = QSignalSpy(self.model.rowsInserted)
        self.model.append_task(tasks[0])
        self.model.append_tasks(tasks[1:])

        self.assertEqual(self.model.rowCount(), 3)
        self.assertEqual(inserted.count(), 2)
        self.assertEqual([inserted.at(0)[1], inserted.at(0)[2]], [0, 0])
        self.assertEqual([inserted.at(1)[1], inserted.at(1)[2]], [1, 2])
        self.assertTrue(all(self.model.task_at(i) is task for i, task in enumerate(tasks)))
        self.assertEqual(self.model.ordered_tasks(), tuple(tasks))
        self.assertEqual(self.model.data(self.model.index(0), Qt.ItemDataRole.DisplayRole), "c.txt")

    def test_snapshot_cannot_change_model_order(self):
        tasks = [Task("first.txt"), Task("second.txt")]
        self.model.append_tasks(tasks)
        snapshot = list(self.model.ordered_tasks())
        snapshot.reverse()
        self.assertIs(self.model.task_at(0), tasks[0])
        self.assertIs(self.model.task_at(1), tasks[1])

    def test_lookup_and_removal_use_object_identity(self):
        first = Task("same.txt")
        second = Task("same.txt")
        self.model.append_tasks([first, second])
        removed = QSignalSpy(self.model.rowsRemoved)

        self.assertEqual(self.model.row_for_task(second), 1)
        self.assertEqual(self.model.row_for_task(Task("same.txt")), -1)
        self.assertTrue(self.model.remove_task(second))
        self.assertEqual(removed.count(), 1)
        self.assertEqual([removed.at(0)[1], removed.at(0)[2]], [1, 1])
        self.assertIs(self.model.task_at(0), first)
        self.assertFalse(self.model.remove_task(second))
        self.assertFalse(self.model.remove_row(9))
        self.assertIsNone(self.model.task_at(9))

    def test_remove_row_and_clear(self):
        tasks = [Task(name) for name in ("a", "b", "c")]
        self.model.append_tasks(tasks)
        removed = QSignalSpy(self.model.rowsRemoved)

        self.assertTrue(self.model.remove_row(1))
        self.assertEqual(self.model.ordered_tasks(), (tasks[0], tasks[2]))
        self.model.clear()
        self.assertEqual(self.model.rowCount(), 0)
        self.assertEqual(removed.count(), 2)
        self.assertEqual([removed.at(1)[1], removed.at(1)[2]], [0, 1])
        self.model.clear()
        self.assertEqual(removed.count(), 2)

    def test_remove_first_middle_last_preserves_order_without_reset(self):
        for row in (0, 2, 4):
            with self.subTest(row=row):
                model = TaskQueueModel()
                tasks = [Task(f"{letter}.txt") for letter in "ABCDE"]
                model.append_tasks(tasks)
                removing = QSignalSpy(model.rowsAboutToBeRemoved)
                removed = QSignalSpy(model.rowsRemoved)
                reset = QSignalSpy(model.modelReset)

                self.assertTrue(model.remove_task(tasks[row]))

                self.assertEqual(model.ordered_tasks(),
                                 tuple(task for task in tasks if task is not tasks[row]))
                self.assertEqual(removing.count(), 1)
                self.assertEqual(removed.count(), 1)
                self.assertEqual([removing.at(0)[1], removing.at(0)[2]], [row, row])
                self.assertEqual([removed.at(0)[1], removed.at(0)[2]], [row, row])
                self.assertEqual(reset.count(), 0)

    def test_clear_emits_one_row_removal_and_empty_clear_is_no_op(self):
        tasks = [Task(f"{letter}.txt") for letter in "ABC"]
        self.model.append_tasks(tasks)
        removing = QSignalSpy(self.model.rowsAboutToBeRemoved)
        removed = QSignalSpy(self.model.rowsRemoved)
        reset = QSignalSpy(self.model.modelReset)

        self.model.clear()

        self.assertEqual(self.model.ordered_tasks(), ())
        self.assertEqual(removing.count(), 1)
        self.assertEqual(removed.count(), 1)
        self.assertEqual([removing.at(0)[1], removing.at(0)[2]], [0, 2])
        self.assertEqual([removed.at(0)[1], removed.at(0)[2]], [0, 2])
        self.assertEqual(reset.count(), 0)

        self.model.clear()
        self.assertEqual(removing.count(), 1)
        self.assertEqual(removed.count(), 1)
        self.assertEqual(reset.count(), 0)

    def test_move_rows_up_and_down_preserves_identity(self):
        tasks = [Task(name) for name in "ABCDE"]
        self.model.append_tasks(tasks)
        moved = QSignalSpy(self.model.rowsMoved)
        root = QModelIndex()

        self.assertTrue(self.model.moveRows(root, 2, 1, root, 0))
        self.assertEqual(self.model.ordered_tasks(), (tasks[2], tasks[0], tasks[1], tasks[3], tasks[4]))
        self.assertEqual(self.model.row_for_task(tasks[1]), 2)
        self.assertTrue(self.model.moveRows(root, 2, 1, root, 5))
        self.assertEqual(self.model.ordered_tasks(), (tasks[2], tasks[0], tasks[3], tasks[4], tasks[1]))
        self.assertIs(self.model.task_at(4), tasks[1])
        self.assertEqual(self.model.row_for_task(tasks[1]), 4)
        self.assertEqual(moved.count(), 2)

    def test_downward_move_uses_qt_destination_child_once(self):
        tasks = [Task(f"{name}.txt") for name in "ABCDE"]
        self.model.append_tasks(tasks)
        moving = QSignalSpy(self.model.rowsAboutToBeMoved)
        moved = QSignalSpy(self.model.rowsMoved)
        reset = QSignalSpy(self.model.modelReset)
        root = QModelIndex()

        self.assertTrue(self.model.moveRows(root, 1, 1, root, 4))

        self.assertEqual(self.model.ordered_tasks(),
                         (tasks[0], tasks[2], tasks[3], tasks[1], tasks[4]))
        self.assertEqual(moving.count(), 1)
        self.assertEqual(moved.count(), 1)
        self.assertEqual([moving.at(0)[1], moving.at(0)[2], moving.at(0)[4]], [1, 1, 4])
        self.assertEqual([moved.at(0)[1], moved.at(0)[2], moved.at(0)[4]], [1, 1, 4])
        self.assertEqual(reset.count(), 0)

    def test_invalid_and_no_op_moves_leave_order_unchanged(self):
        tasks = [Task(name) for name in "ABC"]
        self.model.append_tasks(tasks)
        moved = QSignalSpy(self.model.rowsMoved)
        root = QModelIndex()
        invalid = self.model.index(0)

        for source, count, destination in ((-1, 1, 2), (3, 1, 0), (0, 0, 2), (1, 3, 0), (1, 1, -1), (1, 1, 4), (1, 1, 1), (1, 1, 2)):
            self.assertFalse(self.model.moveRows(root, source, count, root, destination))
        self.assertFalse(self.model.moveRows(invalid, 0, 1, root, 2))
        self.assertFalse(self.model.moveRows(root, 0, 1, invalid, 2))
        self.assertEqual(self.model.ordered_tasks(), tuple(tasks))
        self.assertEqual(moved.count(), 0)

    def test_contiguous_move_updates_persistent_indexes(self):
        tasks = [Task(name) for name in "ABCDE"]
        self.model.append_tasks(tasks)
        persistent_c = QPersistentModelIndex(self.model.index(2))
        root = QModelIndex()

        self.assertTrue(self.model.moveRows(root, 1, 2, root, 5))
        self.assertEqual(self.model.ordered_tasks(), (tasks[0], tasks[3], tasks[4], tasks[1], tasks[2]))
        self.assertEqual(persistent_c.row(), 4)
        self.assertIs(self.model.task_at(persistent_c.row()), tasks[2])

    def test_empty_append_emits_no_insert_signal(self):
        inserted = QSignalSpy(self.model.rowsInserted)
        self.model.append_tasks([])
        self.assertEqual(inserted.count(), 0)
        self.assertEqual(self.model.rowCount(), 0)

    def test_roles_keep_raw_state_and_derive_existing_display_terms(self):
        task = Task("测试001.txt", status="Waiting", progress=17, error_message="reason")
        self.model.append_task(task)
        index = self.model.index(0)

        self.assertIs(self.model.data(index, self.model.TaskRole), task)
        self.assertEqual(self.model.data(index, self.model.NameRole), "测试001.txt")
        self.assertEqual(self.model.data(index, self.model.PathRole), task.path)
        self.assertFalse(self.model.data(index, self.model.IsFolderRole))
        self.assertEqual(self.model.data(index, self.model.StatusRole), "Waiting")
        self.assertEqual(self.model.data(index, self.model.DisplayStatusRole), "Queued")
        self.assertEqual(self.model.data(index, self.model.ProgressRole), 17)
        self.assertEqual(self.model.data(index, self.model.ErrorRole), "reason")
        self.assertTrue(self.model.data(index, self.model.DeletableRole))
        self.assertEqual(self.model.roleNames()[self.model.TaskRole], b"task")

        task.status = "Completed with warnings"
        self.assertEqual(self.model.data(index, self.model.StatusRole), "Completed with warnings")
        self.assertEqual(self.model.data(index, self.model.DisplayStatusRole), "Warning")
        task.status = "Compressing"
        self.assertEqual(self.model.data(index, self.model.DisplayStatusRole), "Compressing")
        self.assertFalse(self.model.data(index, self.model.DeletableRole))
        self.assertEqual(task.status, "Compressing")  # Paused remains UI-only.

    def test_chinese_and_long_paths_are_not_elided_in_model(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            long_path = str(folder / ("很长的中文路径" * 20 + ".txt"))
            file_task = Task(long_path)
            folder_task = Task(str(folder))
            self.model.append_tasks([file_task, folder_task])

            self.assertEqual(self.model.data(self.model.index(0), self.model.PathRole), long_path)
            self.assertEqual(self.model.data(self.model.index(0), self.model.NameRole), Path(long_path).name)
            self.assertTrue(self.model.data(self.model.index(1), self.model.IsFolderRole))
            self.assertIsNone(self.model.data(self.model.index(99), self.model.TaskRole))

    def test_notify_only_current_task_row_after_move(self):
        tasks = [Task(name) for name in "ABC"]
        self.model.append_tasks(tasks)
        changed = QSignalSpy(self.model.dataChanged)
        root = QModelIndex()
        self.assertTrue(self.model.moveRows(root, 0, 1, root, 3))

        tasks[0].progress = 42
        self.assertTrue(self.model.notify_task_changed(tasks[0], [self.model.ProgressRole]))
        self.assertEqual(changed.count(), 1)
        self.assertEqual(changed.at(0)[0].row(), 2)
        self.assertEqual(changed.at(0)[1].row(), 2)
        self.assertEqual(changed.at(0)[2], [self.model.ProgressRole])
        self.assertEqual(self.model.data(self.model.index(2), self.model.ProgressRole), 42)

        self.assertTrue(self.model.remove_task(tasks[0]))
        self.assertFalse(self.model.notify_task_changed(tasks[0]))
        self.assertFalse(self.model.notify_task_changed(Task("A")))
        self.assertEqual(changed.count(), 1)

    def test_notify_without_roles_marks_one_row(self):
        task = Task("one.txt")
        self.model.append_task(task)
        changed = QSignalSpy(self.model.dataChanged)
        self.assertTrue(self.model.notify_task_changed(task))
        self.assertEqual(changed.count(), 1)
        self.assertEqual(changed.at(0)[0].row(), 0)
        self.assertEqual(changed.at(0)[1].row(), 0)


class TaskQueueControllerTests(unittest.TestCase):
    def setUp(self):
        self.model = TaskQueueModel()
        self.controller = TaskQueueController(self.model)

    def fill(self, names):
        tasks = [Task(f"C:/queue/{name}.txt") for name in names]
        self.model.append_tasks(tasks)
        return tasks

    def test_started_marks_only_target_task_compressing(self):
        tasks = self.fill("ABC")
        changed = QSignalSpy(self.model.dataChanged)
        reset = QSignalSpy(self.model.modelReset)

        self.controller.on_task_started(tasks[1])

        self.assertEqual(tasks[1].status, "Compressing")
        self.assertEqual(self.model.ordered_tasks(), tuple(tasks))
        self.assertEqual(
            [id(task) for task in self.model.ordered_tasks()],
            [id(task) for task in tasks],
        )
        self.assertEqual(
            self.model.data(self.model.index(1), TaskQueueModel.StatusRole),
            "Compressing",
        )
        self.assertFalse(
            self.model.data(self.model.index(1), TaskQueueModel.DeletableRole)
        )
        self.assertEqual(changed.count(), 1)
        self.assertEqual(changed.at(0)[0].row(), 1)
        self.assertEqual(changed.at(0)[1].row(), 1)
        self.assertTrue(
            {TaskQueueModel.StatusRole, TaskQueueModel.DisplayStatusRole,
             TaskQueueModel.DeletableRole} <= set(changed.at(0)[2])
        )
        self.assertEqual(reset.count(), 0)

    def test_progress_updates_only_target_task(self):
        tasks = self.fill("ABC")
        tasks[1].status = "Compressing"
        changed = QSignalSpy(self.model.dataChanged)
        reset = QSignalSpy(self.model.modelReset)

        self.controller.on_task_progress(tasks[1], 42)

        self.assertEqual([task.progress for task in tasks], [0, 42, 0])
        self.assertEqual(
            self.model.data(self.model.index(1), TaskQueueModel.ProgressRole), 42
        )
        self.assertEqual(changed.count(), 1)
        self.assertEqual(changed.at(0)[0].row(), 1)
        self.assertEqual(changed.at(0)[1].row(), 1)
        self.assertEqual(list(changed.at(0)[2]), [TaskQueueModel.ProgressRole])
        self.assertEqual(self.model.ordered_tasks(), tuple(tasks))
        self.assertEqual(reset.count(), 0)

    def test_terminal_updates_publish_derived_roles_once(self):
        cases = (
            ("Completed", 100, ""),
            ("Completed with warnings", 100, "partial"),
            ("Failed", 0, "boom"),
            ("Cancelled", 0, ""),
        )
        for result, expected_progress, message in cases:
            with self.subTest(result=result):
                self.model.clear()
                tasks = self.fill("ABC")
                tasks[1].status = "Compressing"
                tasks[1].error_message = message
                changed = QSignalSpy(self.model.dataChanged)
                reset = QSignalSpy(self.model.modelReset)

                if result == "Cancelled":
                    self.controller.on_task_cancelled(tasks[1])
                else:
                    self.controller.on_task_finished(tasks[1], result)

                index = self.model.index(1)
                self.assertEqual(tasks[1].status, result)
                self.assertEqual(tasks[1].progress, expected_progress)
                self.assertEqual(
                    self.model.data(index, TaskQueueModel.StatusRole), result
                )
                self.assertEqual(
                    self.model.data(index, TaskQueueModel.ProgressRole),
                    expected_progress,
                )
                self.assertTrue(
                    self.model.data(index, TaskQueueModel.DeletableRole)
                )
                self.assertEqual(
                    self.model.data(index, TaskQueueModel.ErrorRole), message
                )
                self.assertEqual(
                    self.model.data(index, Qt.ItemDataRole.ToolTipRole),
                    message or tasks[1].path,
                )
                self.assertTrue(
                    {TaskQueueModel.StatusRole, TaskQueueModel.DisplayStatusRole,
                     TaskQueueModel.DeletableRole, TaskQueueModel.ProgressRole,
                     TaskQueueModel.ErrorRole, int(Qt.ItemDataRole.ToolTipRole)}
                    <= set(changed.at(0)[2])
                )
                self.assertEqual(changed.count(), 1)
                self.assertEqual(changed.at(0)[0].row(), 1)
                self.assertEqual(changed.at(0)[1].row(), 1)
                self.assertEqual(reset.count(), 0)

    def test_lifecycle_keeps_identity_order_and_never_resets(self):
        tasks = self.fill("ABC")
        changed = QSignalSpy(self.model.dataChanged)
        reset = QSignalSpy(self.model.modelReset)

        self.controller.on_task_started(tasks[2])
        self.controller.on_task_progress(tasks[2], 10)
        self.controller.on_task_progress(tasks[2], 55)
        self.controller.on_task_finished(tasks[2], "Completed with warnings")

        self.assertEqual(changed.count(), 4)
        self.assertEqual(reset.count(), 0)
        self.assertEqual(self.model.ordered_tasks(), tuple(tasks))
        self.assertEqual(
            [id(task) for task in self.model.ordered_tasks()],
            [id(task) for task in tasks],
        )
        self.assertEqual(tasks[2].status, "Completed with warnings")
        self.assertEqual(tasks[2].progress, 100)
        self.assertEqual(
            self.model.data(self.model.index(2), TaskQueueModel.DisplayStatusRole),
            "Warning",
        )

    def test_updates_for_task_outside_model_emit_nothing(self):
        changed = QSignalSpy(self.model.dataChanged)
        stranger = Task("C:/stranger.txt")

        self.controller.on_task_progress(stranger, 5)
        self.controller.on_task_started(stranger)

        self.assertEqual(changed.count(), 0)
        self.assertEqual(stranger.progress, 5)
        self.assertEqual(stranger.status, "Compressing")

    def test_controller_targets_correct_identity_after_reorder(self):
        tasks = self.fill("ABC")
        root = QModelIndex()
        self.assertTrue(self.model.moveRows(root, 0, 1, root, 3))
        changed = QSignalSpy(self.model.dataChanged)

        self.controller.on_task_progress(tasks[0], 77)

        self.assertEqual(self.model.row_for_task(tasks[0]), 2)
        self.assertEqual(changed.count(), 1)
        self.assertEqual(changed.at(0)[0].row(), 2)
        self.assertEqual(
            self.model.data(self.model.index(2), TaskQueueModel.ProgressRole), 77
        )
        self.assertEqual(
            [id(task) for task in self.model.ordered_tasks()],
            [id(task) for task in (tasks[1], tasks[2], tasks[0])],
        )


if __name__ == "__main__":
    unittest.main()
