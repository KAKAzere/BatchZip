from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, Qt

from core.task import Task


class TaskQueueModel(QAbstractListModel):
    """Ordered model of queue Tasks and the authoritative source for queue
    membership, order, identity lookup, and task data roles."""

    TaskRole = int(Qt.ItemDataRole.UserRole) + 1
    NameRole = TaskRole + 1
    PathRole = TaskRole + 2
    IsFolderRole = TaskRole + 3
    StatusRole = TaskRole + 4
    DisplayStatusRole = TaskRole + 5
    ProgressRole = TaskRole + 6
    ErrorRole = TaskRole + 7
    DeletableRole = TaskRole + 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks: list[Task] = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._tasks)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._tasks):
            return None
        task = self._tasks[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return task.name
        if role == Qt.ItemDataRole.ToolTipRole:
            return task.error_message or task.path
        if role == self.TaskRole:
            return task
        if role == self.NameRole:
            return task.name
        if role == self.PathRole:
            return task.path
        if role == self.IsFolderRole:
            return task.is_folder
        if role == self.StatusRole:
            return task.status
        if role == self.DisplayStatusRole:
            # Paused is transient UI presentation; Task.status remains Compressing.
            return {"Waiting": "Queued", "Completed with warnings": "Warning"}.get(
                task.status, task.status
            )
        if role == self.ProgressRole:
            return task.progress
        if role == self.ErrorRole:
            return task.error_message
        if role == self.DeletableRole:
            return task.status != "Compressing"
        return None

    def roleNames(self):
        names = super().roleNames()
        names.update({
            self.TaskRole: QByteArray(b"task"),
            self.NameRole: QByteArray(b"name"),
            self.PathRole: QByteArray(b"path"),
            self.IsFolderRole: QByteArray(b"isFolder"),
            self.StatusRole: QByteArray(b"status"),
            self.DisplayStatusRole: QByteArray(b"displayStatus"),
            self.ProgressRole: QByteArray(b"progress"),
            self.ErrorRole: QByteArray(b"error"),
            self.DeletableRole: QByteArray(b"deletable"),
        })
        return names

    def append_task(self, task: Task):
        self.append_tasks([task])

    def append_tasks(self, tasks):
        incoming = list(tasks)
        if not incoming:
            return
        start = len(self._tasks)
        self.beginInsertRows(QModelIndex(), start, start + len(incoming) - 1)
        self._tasks.extend(incoming)
        self.endInsertRows()

    def task_at(self, row):
        return self._tasks[row] if 0 <= row < len(self._tasks) else None

    def ordered_tasks(self):
        return tuple(self._tasks)

    def row_for_task(self, task):
        for row, current in enumerate(self._tasks):
            if current is task:
                return row
        return -1

    def remove_task(self, task):
        return self.remove_row(self.row_for_task(task))

    def remove_row(self, row):
        if not 0 <= row < len(self._tasks):
            return False
        self.beginRemoveRows(QModelIndex(), row, row)
        del self._tasks[row]
        self.endRemoveRows()
        return True

    def clear(self):
        if not self._tasks:
            return
        self.beginRemoveRows(QModelIndex(), 0, len(self._tasks) - 1)
        self._tasks.clear()
        self.endRemoveRows()

    def moveRows(self, sourceParent, sourceRow, count, destinationParent, destinationChild):
        size = len(self._tasks)
        if (
            sourceParent.isValid()
            or destinationParent.isValid()
            or count <= 0
            or sourceRow < 0
            or sourceRow + count > size
            or destinationChild < 0
            or destinationChild > size
            or sourceRow <= destinationChild <= sourceRow + count
        ):
            return False
        if not self.beginMoveRows(sourceParent, sourceRow, sourceRow + count - 1,
                                  destinationParent, destinationChild):
            return False
        moved = self._tasks[sourceRow:sourceRow + count]
        del self._tasks[sourceRow:sourceRow + count]
        insertion_row = destinationChild - count if destinationChild > sourceRow else destinationChild
        self._tasks[insertion_row:insertion_row] = moved
        self.endMoveRows()
        return True

    def notify_task_changed(self, task, roles=None):
        row = self.row_for_task(task)
        if row < 0:
            return False
        index = self.index(row)
        self.dataChanged.emit(index, index, list(roles) if roles is not None else [])
        return True
