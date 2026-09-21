import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
                command[:7],
                ["7z", "a", "-tzip", "-y", "-bsp1", "-bso0", "-bse1"],
            )
            self.assertEqual(command[7:], [str(expected), str(source)])


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
            task, output, finished = self.run_compression(
                directory,
                return_code=2,
            )

            self.assertEqual(task.status, "Failed")
            self.assertFalse(output.exists())
            self.assertEqual(finished, [False])

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
            task, output, finished = self.run_compression(
                directory,
                return_code=255,
            )

            self.assertEqual(task.status, "Failed")
            self.assertFalse(output.exists())
            self.assertEqual(finished, [False])
            self.assertIn("Compression Failed", task.error_message)
            self.assertNotIn("Compression Cancelled", task.error_message)

    def test_successful_compression_keeps_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            task, output, finished = self.run_compression(
                directory,
                return_code=0,
            )

            self.assertEqual(task.status, "Completed")
            self.assertTrue(output.exists())
            self.assertEqual(finished, [True])

    @staticmethod
    def run_compression(directory, return_code):
        directory = Path(directory)
        source = directory / "sample.txt"
        source.write_text("test", encoding="utf-8")
        output = directory / "sample.zip"
        process = FinishedProcess(return_code)
        compressor = FinishedCompressor(process, output)
        task = Task(str(source))
        finished = []
        thread = CompressThread([task], "", "zip")
        thread.taskFinished.connect(lambda _, success: finished.append(success))

        with patch("core.compress_thread.Compressor", return_value=compressor):
            thread.run()

        return task, output, finished


class FinishedProcess:
    def __init__(self, return_code):
        self.returncode = return_code
        self.stdout = io.BytesIO()
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


class FinishedCompressor:
    def __init__(self, process, output):
        self.process = process
        self.output = output

    def compress(self, task, output_folder, archive_format):
        self.output.write_bytes(b"partial archive")
        return self.process, str(self.output)

    @staticmethod
    def error_message(return_code):
        return Compressor.error_message(return_code)


class LaunchFailingCompressor:
    @staticmethod
    def compress(task, output_folder, archive_format):
        raise SevenZipLaunchError("raw launch error")


def object_with_path(path):
    class TestTask:
        pass

    task = TestTask()
    task.path = str(path)
    task.status = "Waiting"
    return task


if __name__ == "__main__":
    unittest.main()
