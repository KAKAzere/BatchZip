import os
import queue
import subprocess
import threading
from pathlib import Path

import psutil
from PySide6.QtCore import QThread, Signal

from core.compressor import (
    Compressor,
    InvalidOutputLocationError,
    SevenZipLaunchError,
    SevenZipNotFoundError,
    UnsupportedArchiveFormatError,
)
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
        except SevenZipNotFoundError:
            self.error.emit(
                self._user_error(
                    "7-Zip Not Found",
                    "BatchZip could not start the compression program.",
                    "7-Zip may not be installed, or its location could not be detected.",
                    "Install 7-Zip or check the installation, then try again.",
                )
            )
            return
        except Exception:
            self.error.emit(
                self._user_error(
                    "Unable to Start Compression",
                    "BatchZip could not prepare the compression program.",
                    "7-Zip may be unavailable or unable to start.",
                    "Check the 7-Zip installation, then try again.",
                )
            )
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
                except (OSError, RuntimeError, ValueError) as exc:
                    task.status = "Failed"
                    task.progress = 0
                    task.error_message = self._compress_error_message(exc)
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

                while self.process.poll() is None:
                    previous_progress = progress
                    progress = self._drain_output(
                        output_queue,
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
                    self._remove_partial_archive(output_path)
                    task.status = "Failed"
                    task.progress = 0
                    task.error_message = self._failure_message(
                        compressor,
                        self.process.returncode,
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
        except Exception:
            try:
                self._terminate_process()
            except Exception:
                pass

            try:
                if self._current_output_path:
                    self._remove_partial_archive(self._current_output_path)
            finally:
                self._current_output_path = ""
            self.error.emit(
                self._user_error(
                    "Compression Failed",
                    "BatchZip could not continue the compression task.",
                    "The compression program or required files may be unavailable.",
                    "Check the source files and output location, then try again.",
                )
            )

    @staticmethod
    def _user_error(title, what, cause, suggestion):
        return (
            f"{title}\n\nWhat happened:\n{what}\n\n"
            f"Possible reasons:\n{cause}\n\nSuggestion:\n{suggestion}"
        )

    @classmethod
    def _compress_error_message(cls, error):
        if isinstance(error, SevenZipNotFoundError):
            return cls._user_error(
                "7-Zip Not Found",
                "BatchZip could not start the compression program.",
                "- 7-Zip may not be installed, or its location may no longer be available.",
                "Install 7-Zip or check the installation, then try again.",
            )

        if isinstance(error, SevenZipLaunchError):
            return cls._user_error(
                "Unable to Start 7-Zip",
                "7-Zip could not be started.",
                "- Windows blocked the application.\n"
                "- The executable permission is restricted.",
                "Check your 7-Zip installation and permissions, then try again.",
            )

        if isinstance(error, FileNotFoundError):
            return cls._user_error(
                "Source Not Found",
                "BatchZip could not find the file or folder to compress.",
                "- The source may have been moved or deleted.",
                "Confirm that the source still exists, then add the task again.",
            )

        if isinstance(error, PermissionError):
            return cls._user_error(
                "Permission Denied",
                "BatchZip could not read the source or create the archive.",
                "- Your account may not have access to the source or output folder.",
                "Choose files and an output folder you can access, then try again.",
            )

        if isinstance(error, NotADirectoryError):
            return cls._user_error(
                "Invalid Output Location",
                "The selected output path is not a folder.",
                "- The path may point to a file or may no longer be available.",
                "Choose a valid output folder, then try again.",
            )

        if isinstance(error, InvalidOutputLocationError):
            return cls._user_error(
                "Invalid Output Location",
                "BatchZip could not save the archive in the selected location.",
                "- The output folder is inside the folder being compressed.",
                "Choose an output folder outside the source folder, then try again.",
            )

        if isinstance(error, UnsupportedArchiveFormatError):
            return cls._user_error(
                "Unsupported Archive Format",
                "BatchZip could not start this compression task.",
                "- The selected archive format is not supported.",
                "Select ZIP or 7Z, then try again.",
            )

        if isinstance(error, RuntimeError):
            return cls._user_error(
                "Unable to Create Output Folder",
                "BatchZip could not create the selected output folder.",
                "- The path may be invalid, the drive may be unavailable, or write access may be denied.",
                "Check the path and folder permissions, or choose another location.",
            )

        if isinstance(error, OSError):
            return cls._user_error(
                "Unable to Start Compression",
                "BatchZip could not start the 7-Zip compression program.",
                "- 7-Zip may be unavailable, or Windows may have denied access.",
                "Check the 7-Zip installation and folder permissions, then try again.",
            )

        return cls._user_error(
            "Compression Failed",
            "BatchZip could not complete this compression task.",
            "- The source or output location may be unavailable.",
            "Check the source and output folder, then try again.",
        )

    @staticmethod
    def _read_process_output(stream, output_queue):
        if stream is None:
            return

        try:
            for message in iter_output_messages(stream):
                output_queue.put(message)
        finally:
            stream.close()

    def _drain_output(self, output_queue, task, current_progress):
        while True:
            try:
                line = output_queue.get_nowait()
            except queue.Empty:
                break

            progress = extract_progress(line)

            if progress is not None and progress != current_progress:
                current_progress = progress
                task.progress = progress
                self.taskProgress.emit(task, progress)

        return current_progress

    @staticmethod
    def _failure_message(compressor, return_code):
        return compressor.error_message(return_code)

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
