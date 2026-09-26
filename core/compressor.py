import os
from pathlib import Path
import subprocess

from core.detector import find_7z
from core.windows_job import WindowsJobError


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

    def __init__(self, executable=None, job=None):
        self.exe = executable or find_7z()

        if not self.exe:
            raise SevenZipNotFoundError(
                "7-Zip is not installed or could not be found."
            )

        self.process = None
        self.job = job

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
                    "-sccUTF-8",
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

        if self.job is not None:
            try:
                self.job.assign(self.process)
            except WindowsJobError:
                process_stopped = self._stop_unprotected_process(self.process)

                if not process_stopped:
                    raise SevenZipLaunchError(
                        "7-Zip could not be protected by Windows Job Object "
                        "and could not be stopped."
                    ) from None

                raise SevenZipLaunchError(
                    "7-Zip could not be protected by Windows Job Object."
                ) from None

        return self.process, str(output_zip)

    @staticmethod
    def _stop_unprotected_process(process):
        try:
            process.terminate()
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                return False
        except (OSError, subprocess.SubprocessError):
            return False

        try:
            return process.poll() is not None
        except (OSError, subprocess.SubprocessError):
            return False

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
    def error_message(return_code, diagnostic_output=""):
        details = {
            1: (
                "Compression Completed with Warnings",
                "The archive was created, but some files may not have been added.",
                "7-Zip reported a non-fatal warning.",
                "Review the 7-Zip details before using the archive.",
                "Warning",
            ),
            2: (
                "Compression Failed",
                "7-Zip could not complete the archive.",
                "7-Zip reported a fatal error.",
                "Review the 7-Zip details, then check the source and output folder.",
                "Fatal Error",
            ),
            7: (
                "Compression Failed",
                "7-Zip rejected the compression command.",
                "The 7-Zip command line or its arguments were invalid.",
                "Check the 7-Zip installation, then try again.",
                "Command Line Error",
            ),
            8: (
                "Compression Failed",
                "7-Zip did not have enough memory to complete the archive.",
                "There was not enough memory for the operation.",
                "Close other applications or reduce the amount of data, then try again.",
                "Not Enough Memory",
            ),
            255: (
                "Compression Failed",
                "7-Zip stopped before the archive was completed.",
                "7-Zip was interrupted without a BatchZip Cancel request.",
                "Check whether Windows or another application stopped 7-Zip, then try again.",
                "Interrupted",
            ),
        }

        title, what, cause, suggestion, result = details.get(
            return_code,
            (
                "Compression Failed",
                "7-Zip returned an unrecognized failure code.",
                "The archive result cannot be trusted.",
                "Review the 7-Zip details, then try again.",
                "Unknown Error",
            ),
        )
        message = (
            f"{title}\n\n"
            f"What happened:\n{what}\n\n"
            f"Possible reasons:\nReturn Code {return_code}: {result}\n{cause}\n\n"
            f"Suggestion:\n{suggestion}"
        )

        if diagnostic_output:
            message += f"\n\n7-Zip details:\n{diagnostic_output}"

        return message
