import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from qfluentwidgets import setThemeColor
from core.version import APP_VERSION
from ui.main_window import MainWindow

# --- BatchZip brand accent -------------------------------------------------
# Sampled from assets/icon/app_icon.svg so the interface accent is the product
# icon's own colour instead of the Qt-Fluent default teal (#009faa), which is
# what every control was picking up before.
#
#   ACCENT_PRIMARY  #0F5DDA  icon background gradient, offset 0.58
#   ACCENT_LIGHT    #4FA3FF  icon background gradient, offset 1.00
#   ACCENT_DEEP     #081B4B  icon background gradient, offset 0.00
#
# Only ACCENT_PRIMARY is pushed into qfluentwidgets: it derives the hover,
# pressed, focused and disabled steps from it, so the whole app keeps exactly
# one continuous accent ramp. The other two are the fixed brand endpoints used
# where a single colour has to be written down (status badges).
ACCENT_PRIMARY = "#0F5DDA"
ACCENT_LIGHT = "#4FA3FF"
ACCENT_DEEP = "#081B4B"


def resource_path(relative_path):
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_path / relative_path


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("BatchZip")
    app.setApplicationDisplayName("BatchZip")
    app.setApplicationVersion(APP_VERSION)

    # One accent for every control: Start, Browse, Choose Files / Folder,
    # Clear All, the view toggle, the format selector, and all of their
    # hover / pressed / focused / disabled states.
    setThemeColor(ACCENT_PRIMARY)

    icon_path = resource_path("assets/icon/app_icon.ico")

    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

