from dataclasses import dataclass
from pathlib import Path


@dataclass
class Task:
    path: str
    status: str = "Waiting"
    progress: int = 0
    output_path: str = ""
    error_message: str = ""
    compact: bool = False

    @property
    def name(self):
        return Path(self.path).name

    @property
    def is_folder(self):
        return Path(self.path).is_dir()

    @property
    def size(self):
        if self.is_folder:
            return "Folder"

        try:
            size = Path(self.path).stat().st_size
        except OSError:
            return "Unknown"

        units = ["B", "KB", "MB", "GB", "TB"]
        i = 0

        while size >= 1024 and i < len(units) - 1:
            size /= 1024
            i += 1

        return f"{size:.1f} {units[i]}"
