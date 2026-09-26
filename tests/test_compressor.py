import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QLabel
from qfluentwidgets import PushButton, StrongBodyLabel

from core.compressor import (
    Compressor,
    InvalidOutputLocationError,
    SevenZipLaunchError,
    SevenZipNotFoundError,
    UnsupportedArchiveFormatError,
)
from core.compress_thread import CompressThread
from core.progress import extract_progress, iter_output_messages
from core.task import Task
from core.windows_job import WindowsJob, WindowsJobError
from ui.complete_dialog import CompleteDialog, WarningArchiveDialog
from ui.main_window import MainWindow


class CompressorPathTests(unittest.TestCase):
    @patch("core.compressor.find_7z", return_value=None)
    def test_reports_missing_7zip_during_detection(self, find_7z):
        with self.assertRaises(SevenZipNotFoundError):
            Compressor()

    def test_uses_requested_name_when_available(self):
        with tempfile.TemporaryDirectory() as directory:
            result = Compressor._unique_output_path(
                Path(directory), "report", "zip"
            )

            self.assertEqual(result, Path(directory) / "report.zip")

    def test_adds_counter_when_archive_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "report.zip").touch()
            (folder / "report (2).zip").touch()

            result = Compressor._unique_output_path(folder, "report", "zip")

            self.assertEqual(result, folder / "report (3).zip")

    def test_rejects_unknown_archive_format(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sample.txt"
            source.write_text("test", encoding="utf-8")
            compressor = Compressor(executable="7z")

            with self.assertRaises(UnsupportedArchiveFormatError):
                compressor.compress(object_with_path(source), archive_format="rar")

    def test_rejects_output_folder_inside_source_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            output = source / "output"
            compressor = Compressor(executable="7z")

            with self.assertRaises(InvalidOutputLocationError):
                compressor.compress(
                    object_with_path(source),
                    output_folder=output,
                )

            self.assertFalse(output.exists())

    def test_reports_missing_source_separately(self):
        compressor = Compressor(executable="7z")

        with self.assertRaises(FileNotFoundError):
            compressor.compress(object_with_path("missing.txt"))

    @patch("core.compressor.subprocess.Popen", side_effect=FileNotFoundError)
    def test_reports_missing_7zip_at_launch_separately(self, popen):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sample.txt"
            source.write_text("test", encoding="utf-8")
            compressor = Compressor(executable="7z")

            with self.assertRaises(SevenZipNotFoundError):
                compressor.compress(object_with_path(source))

    @patch("core.compressor.subprocess.Popen", side_effect=PermissionError)
    def test_reports_7zip_launch_failure_separately(self, popen):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sample.txt"
            source.write_text("test", encoding="utf-8")
            compressor = Compressor(executable="7z")

            with self.assertRaises(SevenZipLaunchError):
                compressor.compress(object_with_path(source))

    @patch("core.compressor.subprocess.Popen")
    def test_compress_launches_7zip_with_unique_output(self, popen):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "report.txt"
            source.write_text("test", encoding="utf-8")
            (folder / "report.zip").touch()
            expected = folder / "report (2).zip"
            fake_process = object()
            popen.return_value = fake_process
            compressor = Compressor(executable="7z")

            process, output = compressor.compress(
                object_with_path(source),
                archive_format="zip",
            )

            self.assertIs(process, fake_process)
            self.assertEqual(output, str(expected))
            command = popen.call_args.args[0]
            self.assertEqual(
                command[:8],
                [
                    "7z",
                    "a",
                    "-tzip",
                    "-y",
                    "-bsp1",
                    "-bso0",
                    "-bse1",
                    "-sccUTF-8",
                ],
            )
            self.assertEqual(command[8:], [str(expected), str(source)])

    @patch("core.compressor.subprocess.Popen")
    def test_job_assignment_failure_stops_new_process(self, popen):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sample.txt"
            source.write_text("test", encoding="utf-8")
            process = AssignmentFailureProcess()
            popen.return_value = process
            compressor = Compressor(
                executable="7z",
                job=AssignmentFailingJob(),
            )

            with self.assertRaises(SevenZipLaunchError):
                compressor.compress(object_with_path(source))

            self.assertTrue(process.terminated)
            self.assertTrue(process.waited)


@unittest.skipUnless(os.name == "nt", "Windows Job Object test")
class WindowsJobTests(unittest.TestCase):
    def test_independent_jobs_only_terminate_their_own_processes(self):
        processes = [self._start_sleeper() for _ in range(3)]
        first_job = WindowsJob()
        second_job = WindowsJob()

        try:
            first_job.assign(processes[0])
            second_job.assign(processes[1])

            first_job.close()
            processes[0].wait(timeout=5)

            self.assertIsNone(processes[1].poll())
            self.assertIsNone(processes[2].poll())

            second_job.close()
            processes[1].wait(timeout=5)

            self.assertIsNone(processes[2].poll())
        finally:
            first_job.close()
            second_job.close()

            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)

    @staticmethod
    def _start_sleeper():
        return subprocess.Popen(
            [
                sys.executable,
                "-B",
                "-c",
                "import time; time.sleep(30)",
            ],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )


class ProgressParserTests(unittest.TestCase):
    def test_extracts_7zip_progress(self):
        self.assertEqual(extract_progress(" 42% 8 + example.txt"), 42)

    def test_uses_last_percentage(self):
        self.assertEqual(extract_progress(" 10% 20% 87%"), 87)

    def test_accepts_zero_and_one_hundred(self):
        self.assertEqual(extract_progress("0%"), 0)
        self.assertEqual(extract_progress("100%"), 100)

    def test_rejects_invalid_percentage(self):
        self.assertIsNone(extract_progress("No progress available"))
        self.assertIsNone(extract_progress("101%"))

    def test_splits_carriage_return_progress_stream(self):
        stream = io.BytesIO(b" 0%\r 25%\r 75%\r100%\n")

        self.assertEqual(
            list(iter_output_messages(stream)),
            [" 0%", " 25%", " 75%", "100%"],
        )

    def test_decodes_english_utf8_output(self):
        stream = io.BytesIO(b"WARNING: file is locked\n")

        self.assertEqual(
            list(iter_output_messages(stream)),
            ["WARNING: file is locked"],
        )

    def test_decodes_chinese_utf8_path_without_replacement_characters(self):
        message = r"F:\99_Temp (临时文件)\BatchZipTest\2.txt"
        stream = io.BytesIO((message + "\n").encode("utf-8"))

        result = list(iter_output_messages(stream))

        self.assertEqual(result, [message])
        self.assertNotIn("�", result[0])

    def test_decodes_mixed_utf8_warning_and_keeps_progress(self):
        message = " 42% WARNING: 无法读取 文件.txt"
        stream = io.BytesIO((message + "\r").encode("utf-8"))

        result = list(iter_output_messages(stream))

        self.assertEqual(result, [message])
        self.assertEqual(extract_progress(result[0]), 42)
        self.assertNotIn("�", result[0])


class CompressThreadFailureTests(unittest.TestCase):
    def test_7zip_launch_failure_uses_launch_message(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sample.txt"
            source.write_text("test", encoding="utf-8")
            task = Task(str(source))
            thread = CompressThread([task], "", "zip")

            with patch(
                "core.compress_thread.Compressor",
                return_value=LaunchFailingCompressor(),
            ):
                thread.run()

            self.assertEqual(task.status, "Failed")
            self.assertIn("Unable to Start 7-Zip", task.error_message)
            self.assertIn("What happened:", task.error_message)
            self.assertIn("Possible reasons:", task.error_message)
            self.assertIn("Suggestion:", task.error_message)
            self.assertNotIn("Source Not Found", task.error_message)

    def test_failed_compression_removes_partial_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            task, output, finished, _ = self.run_compression(
                directory,
                return_code=2,
            )

            self.assertEqual(task.status, "Failed")
            self.assertFalse(output.exists())
            self.assertEqual(finished, ["Failed"])

    def test_warning_keeps_archive_and_reports_separate_result(self):
        with tempfile.TemporaryDirectory() as directory:
            task, output, finished, summary = self.run_compression(
                directory,
                return_code=1,
                process_output=b" 25% WARNING: file is locked\r",
            )

            self.assertEqual(task.status, "Completed with warnings")
            self.assertEqual(task.progress, 100)
            self.assertEqual(task.output_path, str(output))
            self.assertTrue(output.exists())
            self.assertEqual(finished, ["Completed with warnings"])
            self.assertEqual(summary, [(0, 1, 0)])
            self.assertIn("Return Code 1", task.error_message)
            self.assertIn("WARNING: file is locked", task.error_message)
            self.assertNotIn("25%", task.error_message)

    def test_known_failure_codes_include_specific_diagnostics(self):
        cases = (
            (2, "Fatal Error"),
            (7, "Command Line Error"),
            (8, "Not Enough Memory"),
            (255, "Interrupted"),
        )

        for return_code, description in cases:
            with self.subTest(return_code=return_code):
                with tempfile.TemporaryDirectory() as directory:
                    task, output, finished, summary = self.run_compression(
                        directory,
                        return_code=return_code,
                        process_output=b"ERROR: diagnostic detail\n",
                    )

                    self.assertEqual(task.status, "Failed")
                    self.assertFalse(output.exists())
                    self.assertEqual(finished, ["Failed"])
                    self.assertEqual(summary, [(0, 0, 1)])
                    self.assertIn(
                        f"Return Code {return_code}",
                        task.error_message,
                    )
                    self.assertIn(description, task.error_message)
                    self.assertIn(
                        "ERROR: diagnostic detail",
                        task.error_message,
                    )

    def test_unknown_failure_code_is_reported_and_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            task, output, finished, summary = self.run_compression(
                directory,
                return_code=42,
                process_output=b"Unexpected diagnostic\n",
            )

            self.assertEqual(task.status, "Failed")
            self.assertFalse(output.exists())
            self.assertEqual(finished, ["Failed"])
            self.assertEqual(summary, [(0, 0, 1)])
            self.assertIn("Return Code 42", task.error_message)
            self.assertIn("Unexpected diagnostic", task.error_message)

    def test_diagnostic_buffer_is_bounded_and_marks_truncation(self):
        diagnostic_output = b"".join(
            f"error line {index:03d} ".encode() + (b"x" * 400) + b"\n"
            for index in range(100)
        )

        with tempfile.TemporaryDirectory() as directory:
            task, _, _, _ = self.run_compression(
                directory,
                return_code=2,
                process_output=diagnostic_output,
            )

            self.assertIn("only the last part is shown", task.error_message)
            self.assertIn("error line 099", task.error_message)
            self.assertNotIn("error line 000", task.error_message)
            self.assertLess(len(task.error_message), 20000)

    def test_unexpected_error_removes_current_archive_and_clears_path(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "sample.txt"
            source.write_text("test", encoding="utf-8")
            output = directory / "sample.zip"
            process = UnexpectedFailureProcess()
            compressor = FinishedCompressor(process, output)
            task = Task(str(source))
            errors = []
            thread = CompressThread([task], "", "zip")
            thread.error.connect(errors.append)

            with patch("core.compress_thread.Compressor", return_value=compressor):
                thread.run()

            self.assertFalse(output.exists())
            self.assertEqual(thread._current_output_path, "")
            self.assertEqual(len(errors), 1)

    def test_non_user_255_is_reported_as_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            task, output, finished, _ = self.run_compression(
                directory,
                return_code=255,
            )

            self.assertEqual(task.status, "Failed")
            self.assertFalse(output.exists())
            self.assertEqual(finished, ["Failed"])
            self.assertIn("Compression Failed", task.error_message)
            self.assertNotIn("Compression Cancelled", task.error_message)

    def test_user_cancel_does_not_require_return_code_255(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "sample.txt"
            source.write_text("test", encoding="utf-8")
            output = directory / "sample.zip"
            task = Task(str(source))
            cancelled = []
            thread = CompressThread([task], "", "zip")
            process = CancelOnPollProcess(thread)
            compressor = FinishedCompressor(process, output)
            thread.taskCancelled.connect(lambda current: cancelled.append(current))

            with patch("core.compress_thread.Compressor", return_value=compressor):
                thread.run()

            self.assertEqual(process.returncode, 42)
            self.assertEqual(task.status, "Cancelled")
            self.assertFalse(output.exists())
            self.assertEqual(cancelled, [task])

    def test_successful_compression_keeps_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            task, output, finished, _ = self.run_compression(
                directory,
                return_code=0,
            )

            self.assertEqual(task.status, "Completed")
            self.assertTrue(output.exists())
            self.assertEqual(finished, ["Completed"])

    @staticmethod
    def run_compression(directory, return_code, process_output=b""):
        directory = Path(directory)
        source = directory / "sample.txt"
        source.write_text("test", encoding="utf-8")
        output = directory / "sample.zip"
        process = FinishedProcess(return_code, process_output)
        compressor = FinishedCompressor(process, output)
        task = Task(str(source))
        finished = []
        summary = []
        thread = CompressThread([task], "", "zip")
        thread.taskFinished.connect(lambda _, result: finished.append(result))
        thread.allFinished.connect(
            lambda success, warnings, failed, _: summary.append(
                (success, warnings, failed)
            )
        )

        with patch("core.compress_thread.Compressor", return_value=compressor):
            thread.run()

        return task, output, finished, summary


class WarningResultUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_preserves_warning_status(self):
        task = Task("sample.txt")
        card = SimpleNamespace(updateTask=lambda updated: None)
        window = SimpleNamespace(tasks=[task], cards=[card])

        MainWindow.onTaskFinished(
            window,
            task,
            "Completed with warnings",
        )

        self.assertEqual(task.status, "Completed with warnings")
        self.assertEqual(task.progress, 100)

    def test_warning_keep_button_preserves_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "sample.zip"
            archive.write_bytes(b"archive")
            task = self.warning_task(archive)
            dialog = WarningArchiveDialog(task)

            dialog.keepBtn.click()

            self.assertTrue(archive.exists())
            self.assertEqual(task.output_path, str(archive))
            self.assertEqual(task.status, "Completed with warnings")
            self.assertEqual(dialog.archive_action, "kept")

            with patch.object(CompleteDialog, "showWindowsNotification"):
                completion = CompleteDialog(
                    0,
                    1,
                    0,
                    directory,
                    [task],
                    [],
                    {id(task): dialog.archive_action},
                )
            text = self.dialog_text(completion)
            self.assertIn("Archive kept with warnings", text)
            self.assertIn(
                "The incomplete archive was kept.",
                text,
            )
            self.assertNotIn("Incomplete archive deleted", text)
            self.assertLess(
                text.index("Archive kept with warnings"),
                text.index("Task Details"),
            )
            completion.close()

    def test_warning_delete_button_removes_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "sample.zip"
            archive.write_bytes(b"archive")
            task = self.warning_task(archive)
            dialog = WarningArchiveDialog(task)

            dialog.deleteBtn.click()

            self.assertFalse(archive.exists())
            self.assertEqual(task.output_path, "")
            self.assertEqual(task.status, "Completed with warnings")
            self.assertEqual(dialog.archive_action, "deleted")

            with patch.object(CompleteDialog, "showWindowsNotification"):
                completion = CompleteDialog(
                    0,
                    1,
                    0,
                    directory,
                    [task],
                    [],
                    {id(task): dialog.archive_action},
                )
            text = self.dialog_text(completion)
            self.assertIn("Incomplete archive deleted", text)
            self.assertIn(
                "The incomplete archive was deleted successfully.",
                text,
            )
            self.assertNotIn("Archive kept with warnings", text)
            self.assertNotIn(str(archive), text)
            self.assertLess(
                text.index("Incomplete archive deleted"),
                text.index("Task Details"),
            )
            completion.close()

    @patch("ui.complete_dialog.QMessageBox")
    @patch("ui.complete_dialog.Path.unlink", side_effect=PermissionError)
    def test_warning_delete_failure_shows_full_path(
        self,
        unlink,
        message_box_class,
    ):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "sample.zip"
            archive.write_bytes(b"archive")
            task = self.warning_task(archive)
            dialog = WarningArchiveDialog(task)
            message_box_class.return_value.clickedButton.return_value = None

            dialog.deleteBtn.click()

            message_box = message_box_class.return_value
            message = message_box.setText.call_args.args[0]
            self.assertIn(str(archive), message)
            self.assertTrue(archive.exists())
            self.assertEqual(task.output_path, str(archive))
            self.assertEqual(task.status, "Completed with warnings")
            self.assertEqual(dialog.archive_action, "delete_failed")
            button_labels = [
                call.args[0]
                for call in message_box.addButton.call_args_list
            ]
            self.assertEqual(button_labels, ["Open Folder", "Close"])

    def test_warning_dialog_sanitizes_localized_output_and_deduplicates_path(self):
        with tempfile.TemporaryDirectory() as directory:
            affected = Path(directory) / "临时文件" / "中文文件名.txt"
            archive = Path(directory) / "临时文件" / "sample.zip"
            archive.parent.mkdir()
            archive.write_bytes(b"archive")
            task = self.warning_task(archive)
            task.error_message = (
                "Compression Completed with Warnings\n\n"
                "What happened:\nThe archive may be incomplete.\n\n"
                "Possible reasons:\nReturn Code 1: Warning\n\n"
                "Suggestion:\nReview the details.\n\n"
                "7-Zip details:\n"
                f"0M Scan {affected}\n"
                "WARNING: 另一个程序正在使用此文件，进程无法访问。\n"
                f"{affected}\n"
                "WARNINGS for files:\n"
                f"{affected}: 另一个程序正在使用此文件。\n"
                "----------------\n"
                "WARNING: Cannot open 1 file"
            )
            dialog = WarningArchiveDialog(task)

            text = self.dialog_text(dialog)

            self.assertIn("Compression completed with warnings", text)
            self.assertIn(
                "1 file could not be added to the archive.",
                text,
            )
            self.assertIn("Affected file:", text)
            self.assertEqual(text.count(str(affected)), 1)
            self.assertIn("Reason:", text)
            self.assertIn(
                "The file is being used by another process.",
                text,
            )
            self.assertIn(f"Archive:\n{archive}", text)
            self.assertLess(text.index("Reason:"), text.index("Affected file:"))
            self.assertLess(text.index("Affected file:"), text.index("Archive:"))
            self.assertNotIn("另一个程序正在使用此文件", text)
            self.assertNotIn("0M Scan", text)
            self.assertNotIn("WARNINGS for files", text)
            self.assertNotIn("----------------", text)
            self.assertNotIn("WARNING:", text)
            self.assert_compact_warning_spacing(dialog)
            dialog.close()

    def test_warning_dialog_orders_unknown_reason_before_multiple_files(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.txt"
            second = Path(directory) / "second.txt"
            archive = Path(directory) / "sample.zip"
            archive.write_bytes(b"archive")
            task = self.warning_task(archive)
            task.error_message = (
                "Compression Completed with Warnings\n\n"
                "What happened:\nThe archive may be incomplete.\n\n"
                "Possible reasons:\nReturn Code 1: Warning\n\n"
                "Suggestion:\nReview the details.\n\n"
                "7-Zip details:\n"
                f"{first}: Unrecognized warning\n"
                f"{second}: Unrecognized warning"
            )
            dialog = WarningArchiveDialog(task)

            text = self.dialog_text(dialog)

            self.assertIn(
                "7-Zip could not add this file to the archive.",
                text,
            )
            self.assertLess(text.index("Reason:"), text.index("Affected files:"))
            self.assertLess(text.index("Affected files:"), text.index("Archive:"))
            self.assert_compact_warning_spacing(dialog)
            dialog.close()

    def test_deleted_warning_feedback_coexists_with_failed_task(self):
        warning_task = Task("warning.txt")
        warning_task.status = "Completed with warnings"
        warning_task.output_path = ""
        failed_task = Task("failed.txt")
        failed_task.status = "Failed"
        failed_task.error_message = (
            "Compression Failed\n\n"
            "What happened:\nThe archive failed.\n\n"
            "Possible reasons:\nReturn Code 2: Fatal Error\n\n"
            "Suggestion:\nReview the details."
        )

        with patch.object(CompleteDialog, "showWindowsNotification"):
            dialog = CompleteDialog(
                0,
                1,
                1,
                "",
                [warning_task],
                [failed_task],
                {id(warning_task): "deleted"},
            )

        text = self.dialog_text(dialog)
        self.assertIn(
            "Compression completed with warnings and failures",
            text,
        )
        self.assertIn("0 completed · 1 warning · 1 failed", text)
        self.assertIn("Incomplete archive deleted", text)
        self.assertIn("The archive failed.", text)
        dialog.close()

    def test_completion_summary_separates_all_result_counts(self):
        self.assertEqual(
            CompleteDialog._summary_text(2, 1, 3),
            "2 completed · 1 warning · 3 failed",
        )

    def test_completion_dialog_title_and_counts_match_result_mix(self):
        cases = (
            (
                2,
                0,
                0,
                "Compression completed successfully.",
                "2 completed · 0 warnings · 0 failed",
            ),
            (
                0,
                1,
                0,
                "Compression completed with warnings",
                "0 completed · 1 warning · 0 failed",
            ),
            (
                2,
                1,
                0,
                "Compression completed with warnings",
                "2 completed · 1 warning · 0 failed",
            ),
            (
                0,
                0,
                1,
                "Compression completed with failures",
                "0 completed · 0 warnings · 1 failed",
            ),
            (
                2,
                0,
                1,
                "Compression completed with failures",
                "2 completed · 0 warnings · 1 failed",
            ),
            (
                0,
                1,
                1,
                "Compression completed with warnings and failures",
                "0 completed · 1 warning · 1 failed",
            ),
            (
                2,
                1,
                1,
                "Compression completed with warnings and failures",
                "2 completed · 1 warning · 1 failed",
            ),
        )

        for success, warnings, failed, title, summary in cases:
            with self.subTest(
                success=success,
                warnings=warnings,
                failed=failed,
            ):
                with patch.object(
                    CompleteDialog,
                    "showWindowsNotification",
                ):
                    dialog = CompleteDialog(
                        success,
                        warnings,
                        failed,
                        "",
                    )

                labels = dialog.findChildren(StrongBodyLabel)
                self.assertEqual(labels[0].text(), title)
                self.assertEqual(
                    CompleteDialog._summary_text(
                        success,
                        warnings,
                        failed,
                    ),
                    summary,
                )
                dialog.close()

    @staticmethod
    def warning_task(archive):
        task = Task("sample.txt")
        task.status = "Completed with warnings"
        task.progress = 100
        task.output_path = str(archive)
        task.error_message = (
            "Compression Completed with Warnings\n\n"
            "What happened:\nThe archive may be incomplete.\n\n"
            "Possible reasons:\nReturn Code 1: Warning\n\n"
            "Suggestion:\nReview the details.\n\n"
            "7-Zip details:\nWARNING: file is locked"
        )
        return task

    @staticmethod
    def dialog_text(dialog):
        labels = dialog.findChildren(QLabel)
        return "\n".join(label.text() for label in labels)

    def assert_compact_warning_spacing(self, dialog):
        dialog.show()
        self.app.processEvents()
        labels = dialog.findChildren(QLabel)
        title = next(
            label
            for label in labels
            if label.text() == "Compression completed with warnings"
        )
        summary = next(
            label
            for label in labels
            if "could not be added to the archive." in label.text()
        )
        reason_label = next(label for label in labels if label.text() == "Reason:")
        affected_label = next(
            label
            for label in labels
            if label.text() in ("Affected file:", "Affected files:")
        )
        archive_label = next(
            label for label in labels if label.text().startswith("Archive:\n")
        )
        reason_index = labels.index(reason_label)
        affected_index = labels.index(affected_label)
        reason_text = labels[reason_index + 1]
        affected_text = labels[affected_index + 1]
        buttons = dialog.findChildren(PushButton)
        keep_button = next(
            button for button in buttons if button.text() == "Keep Archive"
        )
        delete_button = next(
            button for button in buttons if button.text() == "Delete Archive"
        )

        def gap(upper, lower):
            return lower.geometry().top() - upper.geometry().bottom() - 1

        self.assertGreaterEqual(gap(title, summary), 8)
        self.assertLessEqual(gap(title, summary), 24)
        self.assertGreaterEqual(gap(summary, reason_label), 8)
        self.assertLessEqual(gap(summary, reason_label), 24)
        self.assertGreaterEqual(gap(reason_label, reason_text), 0)
        self.assertLessEqual(gap(reason_label, reason_text), 8)
        self.assertGreaterEqual(gap(affected_label, affected_text), 0)
        self.assertLessEqual(gap(affected_label, affected_text), 8)
        self.assertGreaterEqual(gap(reason_text, affected_label), 14)
        self.assertLessEqual(gap(reason_text, affected_label), 24)
        self.assertGreaterEqual(gap(affected_text, archive_label), 8)
        self.assertLessEqual(gap(affected_text, archive_label), 24)
        self.assertEqual(keep_button.geometry().top(), delete_button.geometry().top())
        self.assertEqual(
            dialog.contentsRect().right() - delete_button.geometry().right(),
            24,
        )
        self.assertEqual(
            dialog.contentsRect().bottom() - delete_button.geometry().bottom(),
            24,
        )
        self.assertGreater(
            reason_text.font().pixelSize(),
            affected_text.font().pixelSize(),
        )


class FinishedProcess:
    def __init__(self, return_code, output=b""):
        self.returncode = return_code
        self.stdout = io.BytesIO(output)
        self.pid = os.getpid()

    def poll(self):
        return self.returncode


class UnexpectedFailureProcess(FinishedProcess):
    def __init__(self):
        super().__init__(return_code=2)
        self.poll_count = 0

    def poll(self):
        self.poll_count += 1

        if self.poll_count == 1:
            return None

        raise RuntimeError("unexpected poll failure")


class CancelOnPollProcess(FinishedProcess):
    def __init__(self, thread):
        super().__init__(return_code=None)
        self.thread = thread
        self.poll_count = 0

    def poll(self):
        self.poll_count += 1

        if self.poll_count == 1:
            self.thread.cancel()

        return self.returncode

    def terminate(self):
        self.returncode = 42

    def wait(self, timeout=None):
        return self.returncode


class FinishedCompressor:
    def __init__(self, process, output):
        self.process = process
        self.output = output

    def compress(self, task, output_folder, archive_format):
        self.output.write_bytes(b"partial archive")
        return self.process, str(self.output)

    @staticmethod
    def error_message(return_code, diagnostic_output=""):
        return Compressor.error_message(return_code, diagnostic_output)


class LaunchFailingCompressor:
    @staticmethod
    def compress(task, output_folder, archive_format):
        raise SevenZipLaunchError("raw launch error")


class AssignmentFailingJob:
    @staticmethod
    def assign(process):
        raise WindowsJobError("assignment failed")


class AssignmentFailureProcess:
    def __init__(self):
        self.terminated = False
        self.waited = False

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.waited = True
        return 1

    def poll(self):
        return 1 if self.terminated else None


def object_with_path(path):
    class TestTask:
        pass

    task = TestTask()
    task.path = str(path)
    task.status = "Waiting"
    return task


if __name__ == "__main__":
    unittest.main()
