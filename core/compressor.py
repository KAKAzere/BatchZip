import os
from pathlib import Path
import subprocess

from core.detector import find_7z


SUPPORTED_FORMATS = {
    "zip": ("zip", "-tzip"),
    "7z": ("7z", "-t7z"),
}


class SevenZipNotFoundError(OSError):
    pass


class SevenZipLaunchError(OSError):
    pass


class UnsupportedArchiveFormatError(ValueError):
    pass


class InvalidOutputLocationError(ValueError):
    pass


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
            raise SevenZipNotFoundError(
                "7-Zip is not installed or could not be found."
            )

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
            raise FileNotFoundError("The input file or folder no longer exists.")

        if archive_format not in SUPPORTED_FORMATS:
            raise UnsupportedArchiveFormatError(
                f"Unsupported archive format: {archive_format}"
            )

        if output_folder:
            output_folder = Path(output_folder)

            if input_path.is_dir() and self._is_inside(
                output_folder,
                input_path,
            ):
                raise InvalidOutputLocationError(
                    "The output folder cannot be inside the folder being compressed."
                )

            try:
                output_folder.mkdir(parents=True, exist_ok=True)
            except PermissionError:
                raise PermissionError("The output folder cannot be created due to insufficient permissions.") from None
            except OSError:
                raise RuntimeError("The output folder could not be created.") from None
        else:
            output_folder = input_path.parent

        if not output_folder.is_dir():
            raise NotADirectoryError("The selected output path is not a folder.")

        ext, archive_type = SUPPORTED_FORMATS[archive_format]
        base_name = input_path.name if input_path.is_dir() else input_path.stem
        output_zip = self._unique_output_path(output_folder, base_name, ext)

        task.status = "Compressing"

        try:
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
        except PermissionError:
            raise SevenZipLaunchError(
                "Windows denied permission to start the compression program."
            ) from None
        except FileNotFoundError:
            raise SevenZipNotFoundError(
                "The 7-Zip program could not be started."
            ) from None
        except OSError:
            raise SevenZipLaunchError(
                "The compression program could not be started."
            ) from None

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
        if return_code == 255:
            return (
                "Compression Failed\n\n"
                "What happened:\n7-Zip stopped before the archive was completed.\n\n"
                "Possible reasons:\n"
                "- 7-Zip was interrupted.\n"
                "- Windows or another application stopped the process.\n\n"
                "Suggestion:\nCheck that 7-Zip can run normally, then try again."
            )

        return (
            "Compression Failed\n\n"
            "What happened:\n7-Zip could not create the archive.\n\n"
            "Possible reasons:\n"
            "- The source could not be read.\n"
            "- The output location is unavailable.\n"
            "- The drive may not have enough free space.\n\n"
            "Suggestion:\nCheck the source, output folder, and available space, then try again."
        )
