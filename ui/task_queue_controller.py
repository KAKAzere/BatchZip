from PySide6.QtCore import Qt

from ui.task_model import TaskQueueModel


class TaskQueueController:
    """Thin adapter that applies runtime task updates to the queue model and
    forwards presentation-only pause state to the queue view."""

    STATUS_ROLES = (
        TaskQueueModel.StatusRole,
        TaskQueueModel.DisplayStatusRole,
        TaskQueueModel.DeletableRole,
    )
    PROGRESS_ROLES = (TaskQueueModel.ProgressRole,)
    ERROR_ROLES = (TaskQueueModel.ErrorRole, int(Qt.ItemDataRole.ToolTipRole))
    TERMINAL_ROLES = STATUS_ROLES + PROGRESS_ROLES + ERROR_ROLES

    def __init__(self, model, view=None):
        self._model = model
        self._view = view

    def on_task_started(self, task):
        task.status = "Compressing"
        self._model.notify_task_changed(task, self.STATUS_ROLES)

    def on_task_progress(self, task, progress):
        task.progress = progress
        self._model.notify_task_changed(task, self.PROGRESS_ROLES)

    def on_task_finished(self, task, result):
        task.status = result
        task.progress = 100 if result in ("Completed", "Completed with warnings") else 0
        self._model.notify_task_changed(task, self.TERMINAL_ROLES)

    def on_task_cancelled(self, task):
        task.status = "Cancelled"
        task.progress = 0
        self._model.notify_task_changed(task, self.TERMINAL_ROLES)

    def set_paused(self, paused):
        if self._view is not None:
            self._view.set_paused(paused)
