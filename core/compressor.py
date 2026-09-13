import os
from pathlib import Path
import subprocess

from core.detector import find_7z


SUPPORTED_FORMATS = {
    "zip": ("zip", "-tzip"),
    "7z": ("7z", "-t7z"),
}


class Compressor:
    """
    调用 7-Zip 执行压缩

    支持：
    - 文件
    - 文件夹
    - 后台线程调用
    - Pause / Resume（由 Worker 通过 psutil 控制进程）
    - ZIP / 7Z 双格式
    """

    def __init__(self, executable=None):
        self.exe = executable or find_7z()

        if not self.exe:
            raise FileNotFoundError("7z.exe not found")

        self.process = None

    def compress(self, task, output_folder=None, archive_format="zip"):
        """
        启动一次压缩，返回 (Popen, output_zip_path)

        Args:
            task: Task 对象
            output_folder: 输出目录(None=原目录)
            archive_format: "zip" 或 "7z"

        Returns:
            (subprocess.Popen, str)
        """

        input_path = Path(task.path)

        if not input_path.exists():
            raise FileNotFoundError(f"Input no longer exists: {input_path}")

        if archive_format not in SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported archive format: {archive_format}")

        if output_folder:
            output_folder = Path(output_folder)

            if input_path.is_dir() and self._is_inside(
                output_folder,
                input_path,
            ):
                raise ValueError(
                    "The output folder cannot be inside the folder being compressed."
                )

            output_folder.mkdir(parents=True, exist_ok=True)
        else:
            output_folder = input_path.parent

        if not output_folder.is_dir():
            raise NotADirectoryError(f"Output folder is not a directory: {output_folder}")

        ext, archive_type = SUPPORTED_FORMATS[archive_format]
        base_name = input_path.name if input_path.is_dir() else input_path.stem
        output_zip = self._unique_output_path(output_folder, base_name, ext)

        task.status = "Compressing"

        self.process = subprocess.Popen(
            [
                self.exe,
                "a",
                archive_type,
                "-y",
                "-bsp1",
                "-bso0",
                "-bse1",
                str(output_zip),
                str(input_path)
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if os.name == "nt"
                else 0
            )
        )

        return self.process, str(output_zip)

    @staticmethod
    def _unique_output_path(output_folder, base_name, extension):
        """Return a new archive path without modifying an existing archive."""

        candidate = output_folder / f"{base_name}.{extension}"
        counter = 2

        while candidate.exists():
            candidate = output_folder / f"{base_name} ({counter}).{extension}"
            counter += 1

        return candidate

    @staticmethod
    def _is_inside(path, parent):
        try:
            path.resolve().relative_to(parent.resolve())
            return True
        except ValueError:
            return False

    @staticmethod
    def error_message(return_code):
        messages = {
            1: "7-Zip completed with warnings.",
            2: "7-Zip reported a fatal error.",
            7: "7-Zip rejected the command line.",
            8: "7-Zip ran out of memory.",
            255: "Compression was cancelled.",
        }
        return messages.get(
            return_code,
            f"7-Zip exited with code {return_code}.",
        )
