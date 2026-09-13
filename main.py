import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow


APP_VERSION = "1.0.0"


def resource_path(relative_path):
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_path / relative_path


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("BatchZip")
    app.setApplicationDisplayName("BatchZip")
    app.setApplicationVersion(APP_VERSION)

    icon_path = resource_path("assets/icon/app_icon.ico")

    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
