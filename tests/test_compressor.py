import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.compressor import Compressor
from core.progress import extract_progress, iter_output_messages


class CompressorPathTests(unittest.TestCase):
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

            with self.assertRaises(ValueError):
                compressor.compress(object_with_path(source), archive_format="rar")

    def test_rejects_output_folder_inside_source_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            output = source / "output"
            compressor = Compressor(executable="7z")

            with self.assertRaises(ValueError):
                compressor.compress(
                    object_with_path(source),
                    output_folder=output,
                )

            self.assertFalse(output.exists())

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


def object_with_path(path):
    class TestTask:
        pass

    task = TestTask()
    task.path = str(path)
    task.status = "Waiting"
    return task


if __name__ == "__main__":
    unittest.main()
