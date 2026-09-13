import os
import queue
import subprocess
import threading
from pathlib import Path

import psutil
from PySide6.QtCore import QThread, Signal

from core.compressor import Compressor
from core.progress import extract_progress, iter_output_messages


class CompressThread(QThread):
    """Run queued 7-Zip jobs without blocking the UI thread."""

    taskStarted = Signal(object)
    taskProgress = Signal(object, int)
    taskFinished = Signal(object, bool)
    taskCancelled = Signal(object)
    overallStatus = Signal(str)
    allFinished = Signal(int, int, str)
    cancelled = Signal()
    error = Signal(str)

    def __init__(self, tasks, output_folder, archive_format="zip"):
        super().__init__()

        self.tasks = list(tasks)
        self.output_folder = output_folder
        self.archive_format = archive_format

        self._running = True
        self._paused = False
        self._cancel_requested = False
        self.process = None
        self._current_output_path = ""

    def run(self):
        try:
            compressor = Compressor()
        except FileNotFoundError:
            self.error.emit(
                "Unable to locate 7z.exe. Install 7-Zip and try again."
            )
            return
        except Exception as exc:
            self.error.emit(f"Unable to initialize 7-Zip: {exc}")
            return

        success = 0
        failed = 0
        first_path = self.tasks[0].path if self.tasks else os.getcwd()
        last_folder = self.output_folder or os.path.dirname(first_path)
        total = len(self.tasks)

        try:
            for index, task in enumerate(self.tasks):
                if not self._running:
                    break

                self.taskStarted.emit(task)
                self.overallStatus.emit(
                    f"{index + 1}/{total} files · Compressing"
                )

                try:
                    self.process, output_path = compressor.compress(
                        task,
                        self.output_folder or None,
                        self.archive_format,
                    )
                except (OSError, ValueError) as exc:
                    task.status = "Failed"
                    task.progress = 0
                    task.error_message = str(exc)
                    failed += 1
                    self.taskFinished.emit(task, False)
                    continue

                self._current_output_path = output_path
                output_queue = queue.Queue()
                reader = threading.Thread(
                    target=self._read_process_output,
                    args=(self.process.stdout, output_queue),
                    daemon=True,
                )
                reader.start()

                try:
                    process_handle = psutil.Process(self.process.pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    process_handle = None

                progress = 0
                output_lines = []

                while self.process.poll() is None:
                    previous_progress = progress
                    progress = self._drain_output(
                        output_queue,
                        output_lines,
                        task,
                        progress,
                    )

                    if progress != previous_progress:
                        self.overallStatus.emit(
                            f"{index + 1}/{total} files · {progress}%"
                        )

                    if not self._running:
                        self._terminate_process()
                        break

                    if self._paused:
                        process_handle = self._suspend_process(process_handle)
                        self.overallStatus.emit(
                            f"{index + 1}/{total} files · Paused"
                        )

                        while self._paused and self._running:
                            self.msleep(100)

                        if not self._running:
                            continue

                        process_handle = self._resume_process(process_handle)

                    self.msleep(50)

                reader.join(timeout=1)
                progress = self._drain_output(
                    output_queue,
                    output_lines,
                    task,
                    progress,
                )

                if not self._running:
                    self._remove_partial_archive(output_path)
                    task.status = "Cancelled"
                    task.progress = 0
                    task.output_path = ""
                    task.error_message = ""
                    self.taskCancelled.emit(task)
                    break

                if self.process.returncode == 0:
                    task.progress = 100
                    task.status = "Completed"
                    task.output_path = output_path
                    task.error_message = ""
                    success += 1
                    last_folder = os.path.dirname(output_path)
                    self.taskProgress.emit(task, 100)
                    self.taskFinished.emit(task, True)
                else:
                    task.status = "Failed"
                    task.progress = 0
                    task.error_message = self._failure_message(
                        compressor,
                        self.process.returncode,
                        output_lines,
                    )
                    failed += 1
                    self.taskFinished.emit(task, False)

                self.process = None
                self._current_output_path = ""

            if self._cancel_requested:
                self.overallStatus.emit("Cancelled")
                self.cancelled.emit()
            elif self._running:
                self.overallStatus.emit("Completed")
                self.allFinished.emit(success, failed, last_folder)
        except Exception as exc:
            self._terminate_process()
            self.error.emit(f"Unexpected compression error: {exc}")

    @staticmethod
    def _read_process_output(stream, output_queue):
        if stream is None:
            return

        try:
            for message in iter_output_messages(stream):
                output_queue.put(message)
        finally:
            stream.close()

    def _drain_output(self, output_queue, output_lines, task, current_progress):
        while True:
            try:
                line = output_queue.get_nowait()
            except queue.Empty:
                break

            output_lines.append(line)
            progress = extract_progress(line)

            if progress is not None and progress != current_progress:
                current_progress = progress
                task.progress = progress
                self.taskProgress.emit(task, progress)

        return current_progress

    @staticmethod
    def _failure_message(compressor, return_code, output_lines):
        base_message = compressor.error_message(return_code)
        details = [
            line.strip()
            for line in output_lines
            if line.strip() and extract_progress(line) is None
        ]

        if not details:
            return base_message

        detail = details[-1]

        if len(detail) > 300:
            detail = detail[-300:]

        return f"{base_message} {detail}"

    @staticmethod
    def _suspend_process(process_handle):
        if process_handle is None:
            return None

        try:
            process_handle.suspend()
            return process_handle
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    @staticmethod
    def _resume_process(process_handle):
        if process_handle is None:
            return None

        try:
            process_handle.resume()
            return process_handle
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def _terminate_process(self):
        if self.process is None or self.process.poll() is not None:
            return

        try:
            self.process.terminate()
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                self.process.kill()
                self.process.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                pass
        except OSError:
            pass

    @staticmethod
    def _remove_partial_archive(output_path):
        try:
            Path(output_path).unlink(missing_ok=True)
        except OSError:
            pass

    def _request_stop(self, cancelled):
        self._cancel_requested = cancelled
        self._running = False
        self._paused = False

        if self.process is not None and self.process.poll() is None:
            try:
                self.process.terminate()
            except OSError:
                pass

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def cancel(self):
        self._request_stop(cancelled=True)

    def stop(self):
        self._request_stop(cancelled=False)
