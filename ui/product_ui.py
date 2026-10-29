"""Product-UI visual language for the BatchZip prototype.

Presentation only. This module owns colours, the folder illustration, the halo
progress bar and button feedback. It never touches the model, the compression
core, the worker, or any interaction semantics.

The palette is taken from the application icon gradient:
    #081B4B  ->  #0F5DDA  ->  #4FA3FF
so the desktop UI and the product mark share one accent family.
"""

import os

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    Qt,
    Property,
)
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget

from qfluentwidgets import isDarkTheme, qconfig

# --- brand ------------------------------------------------------------------
ACCENT_DEEP = "#081B4B"
ACCENT = "#0F5DDA"
ACCENT_LIGHT = "#4FA3FF"

DANGER_LIGHT = "#c0392b"
DANGER_DARK = "#ff99a4"

# --- folder mark -------------------------------------------------------------
# macOS Big Sur folder construction, in the warm gold the product UI uses:
# a darker back panel whose top edge has a SLANTED tab, and a much larger,
# lighter front panel covering roughly the lower four fifths.
FOLDER_BACK_TOP = "#CE8E22"
FOLDER_BACK_BOTTOM = "#BC7E18"
FOLDER_FRONT_TOP = "#FFD166"
FOLDER_FRONT_BOTTOM = "#F1AB37"
FOLDER_PAPER = "#FFFDF6"
FOLDER_PAPER_DARK = "#F3EDDF"
FOLDER_HALO = (242, 174, 60)


def accent_rgb():
    colour = QColor(ACCENT)
    return colour.red(), colour.green(), colour.blue()


def light_rgb():
    colour = QColor(ACCENT_LIGHT)
    return colour.red(), colour.green(), colour.blue()


def danger_color():
    return DANGER_DARK if isDarkTheme() else DANGER_LIGHT


# --- surfaces ---------------------------------------------------------------
# The single source of every BatchZip-owned surface colour.
#
# These constants are only values. Which of them applies is decided by
# isDarkTheme() alone - i.e. by the theme qfluentwidgets has actually resolved
# and applied. BatchZip does not run a second opinion of its own, because that is
# exactly what left the custom surfaces dark while the Fluent controls stayed
# light. The startup seam in MainWindow guarantees that resolved value is correct
# before anything is painted.
PAGE_SURFACE_LIGHT = "#efefef"
PAGE_SURFACE_DARK = "#202020"

# Panels sit one step above the page. In light mode the page value is reused so
# the approved light look does not move; in dark mode the panel lifts to the
# neutral qfluentwidgets itself uses for a dark surface.
PANEL_SURFACE_LIGHT = "#efefef"
PANEL_SURFACE_DARK = "#2b2b2b"

PANEL_BORDER_LIGHT = "rgba(15,40,90,58)"
PANEL_BORDER_DARK = "rgba(255,255,255,40)"

# Plain QLabels (the drop-zone prompt is the only one) take their ink from the Qt
# palette, which qfluentwidgets never updates, so they stay black in dark theme.
# This is the ink those widgets get instead.
TEXT_PRIMARY_LIGHT = "#1a1a1a"
TEXT_PRIMARY_DARK = "#ffffff"


def page_surface():
    """The one background colour of the main page."""
    return PAGE_SURFACE_DARK if isDarkTheme() else PAGE_SURFACE_LIGHT


def panel_surface():
    """Surface for the panels that sit on the page (compression, drop zone)."""
    return PANEL_SURFACE_DARK if isDarkTheme() else PANEL_SURFACE_LIGHT


def panel_border():
    """Low-contrast Fluent border for those panels."""
    return PANEL_BORDER_DARK if isDarkTheme() else PANEL_BORDER_LIGHT


def text_primary():
    """Ink for widgets qfluentwidgets does not style itself."""
    return TEXT_PRIMARY_DARK if isDarkTheme() else TEXT_PRIMARY_LIGHT


class SurfaceWidget(QWidget):
    """A container that paints a theme-resolved surface behind its children.

    The colour is looked up in paintEvent rather than being written into a style
    sheet once, so the surface always matches the theme that is active right now.
    That removes the dependency on the theme signal firing at a particular
    moment, which qfluentwidgets does not guarantee for Theme.AUTO.

    Children paint after the parent, so the fill sits behind them; the widget
    itself never blocks input.
    """

    def __init__(self, surface, parent=None):
        super().__init__(parent)
        self._surface = surface
        # paintEvent reads the theme live, but nothing invalidates this widget
        # when the theme changes: its style sheet is not one qfluentwidgets
        # manages. Without this the surface keeps its old colour until some
        # unrelated event repaints it, which shows up as a half dark window.
        qconfig.themeChanged.connect(self._onThemeChanged)

    def _onThemeChanged(self, *_):
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self._surface()))
        painter.end()
        super().paintEvent(event)


def hairline(alpha=64):
    return (f"rgba(255,255,255,{alpha})" if isDarkTheme()
            else f"rgba(15,40,90,{alpha})")


def accent_alpha(alpha):
    r, g, b = accent_rgb()
    return f"rgba({r},{g},{b},{alpha})"


# --- folder illustration -----------------------------------------------------
class FolderIllustration(QWidget):
    """A modern folder mark for the drop area.

    Drawn from primitives rather than a bitmap so it stays crisp at any DPI and
    needs no asset file. ``peek`` (0..1) is animated: the content sheet rises out
    of the folder, which is what makes hover and drag-over read as "drop it here"
    instead of a colour change.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._peek = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(84, 64)
        self._animation = QPropertyAnimation(self, b"peek", self)
        self._animation.setDuration(170)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def getPeek(self):
        return self._peek

    def setPeek(self, value):
        self._peek = max(0.0, min(1.0, float(value)))
        self.update()

    peek = Property(float, getPeek, setPeek)

    def setActive(self, active):
        """Animate towards the raised state. Interruptible by design."""
        if active == (self._animation.endValue() == 1.0) and self._animation.state():
            return
        self._animation.stop()
        self._animation.setStartValue(self._peek)
        self._animation.setEndValue(1.0 if active else 0.0)
        self._animation.start()

    def resizeTo(self, width):
        """macOS folder proportion, 100 x 87, so it never reads as flat."""
        self.setFixedSize(width, int(width * 0.87))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        scale = self.width() / 100.0
        peek = self._peek
        lift = peek * 1.5
        dark = isDarkTheme()

        def sx(value):
            return value * scale

        def sy(value):
            return (value - lift) * scale

        def box(x, y, w, h):
            return QRectF(sx(x), sy(y), sx(w), sx(h))

        def radius(value):
            return value * scale

        painter.setPen(Qt.PenStyle.NoPen)

        # Design box 100 x 87, taken from the macOS Big Sur folder proportions:
        #   back top (tab)  13.0      diagonal from x 33 -> 42 across the step
        #   back top (body) 20.5
        #   front top       28.5      the front covers the lower 79% of the mark
        #   bottom          87.0
        left, right = 8.0, 93.0
        tab_top = 13.0
        tab_slant_start = 33.0
        body_top = 20.5
        slant_end = 42.0
        front_top = 28.5
        bottom = 87.0
        back_corner = 6.0
        front_corner = 7.5

        # 1. warm halo while a drop is expected (drawn behind everything)
        if peek > 0.01:
            hr, hg, hb = FOLDER_HALO
            painter.setBrush(QColor(hr, hg, hb, int(40 * peek)))
            painter.drawRoundedRect(box(1, 6, 98, 82), radius(19), radius(19))

        # 2. contact shadow
        painter.setBrush(QColor(120, 80, 12, 46 if dark else 36))
        painter.drawRoundedRect(box(14, 84, 73, 4), radius(2), radius(2))

        # 3. back panel. Its top edge runs flat across the tab, then SLANTS down
        #    to the body line. That slanted step is the macOS silhouette; a right
        #    angle there is what made earlier attempts read as a printer.
        path = QPainterPath()
        path.moveTo(sx(left + back_corner), sy(tab_top))
        path.lineTo(sx(tab_slant_start), sy(tab_top))
        path.lineTo(sx(slant_end), sy(body_top))
        path.lineTo(sx(right - back_corner), sy(body_top))
        path.quadTo(sx(right), sy(body_top), sx(right), sy(body_top + back_corner))
        path.lineTo(sx(right), sy(bottom - back_corner))
        path.quadTo(sx(right), sy(bottom), sx(right - back_corner), sy(bottom))
        path.lineTo(sx(left + back_corner), sy(bottom))
        path.quadTo(sx(left), sy(bottom), sx(left), sy(bottom - back_corner))
        path.lineTo(sx(left), sy(tab_top + back_corner))
        path.quadTo(sx(left), sy(tab_top), sx(left + back_corner), sy(tab_top))
        path.closeSubpath()

        back = QLinearGradient(0.0, sy(tab_top), 0.0, sy(bottom))
        back.setColorAt(0.0, QColor(FOLDER_BACK_TOP))
        back.setColorAt(1.0, QColor(FOLDER_BACK_BOTTOM))
        painter.setBrush(back)
        painter.drawPath(path)

        # 4. paper. It rests fully hidden behind the front panel and only rises
        #    into the visible strip as the folder opens, so the closed state stays
        #    a clean macOS silhouette while the hover feedback is kept.
        paper_top = front_top - peek * 7.5
        paper = box(22.0, paper_top, 56.0, 24.0)
        painter.setBrush(QColor(FOLDER_PAPER if not dark else FOLDER_PAPER_DARK))
        painter.drawRoundedRect(paper, radius(4), radius(4))

        # 5. front panel: same width, flat top edge, generous corners.
        front = QLinearGradient(0.0, sy(front_top), 0.0, sy(bottom))
        front.setColorAt(0.0, QColor(FOLDER_FRONT_TOP))
        front.setColorAt(1.0, QColor(FOLDER_FRONT_BOTTOM))
        painter.setBrush(front)
        painter.drawRoundedRect(box(left, front_top, right - left, bottom - front_top),
                                radius(front_corner), radius(front_corner))
        painter.end()


# --- halo progress -----------------------------------------------------------
def paint_halo_bar(painter, rect, ratio, glow=3.0):
    """Rounded gradient bar with a soft halo behind the filled part.

    ``rect`` is the full halo area; the bar itself is inset vertically by
    ``glow`` so the glow can never be clipped by the caller's rectangle. The
    halo is two translucent rounded rects rather than a blur effect, which keeps
    the delegate paint cheap enough for a long queue.
    """
    dark = isDarkTheme()
    radius = max(1.5, (rect.height() - glow * 2) / 2.0)
    track = QRectF(rect).adjusted(0, glow, 0, -glow)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 26) if dark else QColor(15, 40, 90, 22))
    painter.drawRoundedRect(track, radius, radius)

    ratio = max(0.0, min(1.0, float(ratio)))
    if ratio <= 0.0:
        return

    width = max(track.height(), track.width() * ratio)
    filled = QRectF(track.left(), track.top(), width, track.height())
    r, g, b = accent_rgb()

    for spread, alpha in ((2.8, 30 if dark else 24), (1.3, 54 if dark else 44)):
        painter.setBrush(QColor(r, g, b, alpha))
        painter.drawRoundedRect(filled.adjusted(-spread, -spread, spread, spread),
                                radius + spread, radius + spread)

    gradient = QLinearGradient(filled.left(), 0.0, filled.right(), 0.0)
    gradient.setColorAt(0.0, QColor(ACCENT_LIGHT))
    gradient.setColorAt(1.0, QColor(ACCENT))
    painter.setBrush(gradient)
    painter.drawRoundedRect(filled, radius, radius)

    # leading cap highlight: the edge reads as the live progress point
    cap_width = min(filled.width(), radius * 1.3)
    painter.setBrush(QColor(255, 255, 255, 92 if dark else 78))
    painter.drawRoundedRect(
        QRectF(filled.right() - cap_width, filled.top(), cap_width, filled.height()),
        radius, radius)


# --- buttons -----------------------------------------------------------------
# qfluentwidgets reserves the icon slot with an asymmetric left padding, chosen
# by the hasIcon property of the button:
#     PushButton[hasIcon=false] { padding: 5px 12px 6px 12px; }
#     PushButton[hasIcon=true]  { padding: 5px 12px 6px 36px; }
# A custom style sheet replaces that rule, so it has to be reproduced here.
# Without it the icon is painted at its fixed offset while the label starts at
# the much smaller custom padding, and the two land on top of each other.
ICON_PADDING_QSS = 'QPushButton[hasIcon="true"] { padding-left:36px; }'


def button_qss(role):
    """Fluent-looking feedback for one button role.

    Rebuilt per theme because qfluentwidgets applies its own style sheet through
    a theme-keyed property, so a plain override would be lost on theme change.
    """
    dark = isDarkTheme()
    r, g, b = accent_rgb()

    if role == "primary":
        base = QColor(ACCENT)
        hover = QColor(ACCENT).lighter(118)
        press = QColor(ACCENT).darker(126)
        return (
            "QPushButton {"
            f"color:#ffffff; background-color:{base.name()};"
            "border:1px solid rgba(255,255,255,46); border-radius:7px;"
            "padding:5px 20px 5px 12px; font-weight:600; }"
            + ICON_PADDING_QSS
            + f"QPushButton:hover {{ background-color:{hover.name()};"
            "border:1px solid rgba(255,255,255,86); }"
            f"QPushButton:pressed {{ background-color:{press.name()};"
            "padding-top:6px; padding-bottom:4px;"
            "border:1px solid rgba(255,255,255,30); }"
            "QPushButton:disabled {"
            + (f"color:rgba(255,255,255,120); background-color:rgba({r},{g},{b},64);"
               "border:1px solid transparent; }" if dark else
               "color:rgba(120,120,120,150); background-color:rgba(120,120,120,34);"
               "border:1px solid transparent; }")
            + "QPushButton:focus { outline:none; }"
        )

    if role == "quiet":
        return (
            "QPushButton {"
            + (f"color:#e8e8e8; border:1px solid rgba(255,255,255,70);"
               if dark else "color:#1b1b1b; border:1px solid rgba(15,40,90,60);")
            + "background-color:transparent; border-radius:7px;"
            "padding:5px 14px 5px 12px; }"
            + ICON_PADDING_QSS
            + f"QPushButton:hover {{ background-color:rgba({r},{g},{b},"
            + ("46" if dark else "26") + "); "
            + (f"border:1px solid rgba({r},{g},{b},150); }}"
               if dark else f"border:1px solid rgba({r},{g},{b},140); }}")
            + f"QPushButton:pressed {{ background-color:rgba({r},{g},{b},"
            + ("74" if dark else "54") + "); "
            "padding-top:6px; padding-bottom:4px; }"
            "QPushButton:disabled {"
            + ("color:rgba(255,255,255,90); border:1px solid rgba(255,255,255,34);"
               if dark else "color:rgba(120,120,120,140);"
                            "border:1px solid rgba(120,120,120,40);")
            + "background-color:transparent; }"
            "QPushButton:focus { outline:none; }"
        )

    # danger-ish secondary, used by Cancel
    danger = QColor(danger_color())
    return (
        "QPushButton {"
        + (f"color:#e8e8e8; border:1px solid rgba(255,255,255,70);"
           if dark else "color:#1b1b1b; border:1px solid rgba(15,40,90,60);")
        + "background-color:transparent; border-radius:7px; padding:5px 14px 5px 12px; }"
        + ICON_PADDING_QSS
        + f"QPushButton:hover {{ background-color:rgba({danger.red()},{danger.green()},"
        f"{danger.blue()}," + ("46" if dark else "26") + f");"
        f"border:1px solid rgba({danger.red()},{danger.green()},{danger.blue()},150); }}"
        f"QPushButton:pressed {{ background-color:rgba({danger.red()},{danger.green()},"
        f"{danger.blue()}," + ("74" if dark else "54") + ");"
        "padding-top:6px; padding-bottom:4px; }"
        "QPushButton:disabled {"
        + ("color:rgba(255,255,255,90); border:1px solid rgba(255,255,255,34);"
           if dark else "color:rgba(120,120,120,140);"
                        "border:1px solid rgba(120,120,120,40);")
        + "background-color:transparent; }"
        "QPushButton:focus { outline:none; }"
    )


def apply_button_style(button, role):
    button.setStyleSheet(button_qss(role))


# --- supplied svg icon --------------------------------------------------------
SETTINGS_SVG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets", "icons", "settings.svg")

# Neutral at rest, stronger on hover. Chosen from the surface the glyph actually
# sits on rather than from the theme flag: the deferred "page keeps a light
# background in dark theme" issue means those two can disagree, and picking by
# theme alone would wash the icon out.
SETTINGS_INK_ON_LIGHT = {"normal": "#5A6270", "hover": "#2B3340"}
SETTINGS_INK_ON_DARK = {"normal": "#C8CDD6", "hover": "#FFFFFF"}


def ink_for_surface(surface):
    """Pick the settings glyph ink that contrasts with `surface`."""
    colour = QColor(surface)
    luma = 0.2126 * colour.redF() + 0.7152 * colour.greenF() + 0.0722 * colour.blueF()
    return SETTINGS_INK_ON_LIGHT if luma > 0.5 else SETTINGS_INK_ON_DARK


def svg_pixmap(svg_path, color, size, dpr=2.0):
    """Render an SVG at ``size`` and tint it with ``color``.

    The supplied file is used exactly as given - its path data is never edited.
    The tint is composited onto the rendered pixmap, which is what lets one
    colourless SVG serve every theme and interaction state.
    """
    renderer = QSvgRenderer(svg_path)
    if not renderer.isValid():
        return None
    pixmap = QPixmap(int(size * dpr), int(size * dpr))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(color))
    painter.end()
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def settings_icon(size=20, surface=None):
    """Two-state icon for the settings button: Normal + Active (hover)."""
    ink = ink_for_surface(surface) if surface is not None else (
        SETTINGS_INK_ON_DARK if isDarkTheme() else SETTINGS_INK_ON_LIGHT)
    icon = QIcon()
    normal = svg_pixmap(SETTINGS_SVG, ink["normal"], size)
    hover = svg_pixmap(SETTINGS_SVG, ink["hover"], size)
    if normal is not None:
        icon.addPixmap(normal, QIcon.Mode.Normal, QIcon.State.Off)
    if hover is not None:
        icon.addPixmap(hover, QIcon.Mode.Active, QIcon.State.Off)
    return icon


def settings_button_qss():
    """Bare at rest, accent soft on hover, deeper while pressed."""
    r, g, b = accent_rgb()
    dark = isDarkTheme()
    return (
        "QToolButton { background:transparent; border:none; border-radius:7px; }"
        f"QToolButton:hover {{ background:rgba({r},{g},{b},{44 if dark else 26}); }}"
        f"QToolButton:pressed {{ background:rgba({r},{g},{b},{74 if dark else 50}); }}"
        "QToolButton:focus { outline:none; }"
    )


def drop_zone_qss(active):
    """Dashed drop target. Accent-tinted and softly filled while active."""
    r, g, b = accent_rgb()
    # The prompt is a plain QLabel, so it inherits the Qt palette and would stay
    # black on a dark surface; the colour is supplied here instead.
    _DROP_ZONE_LABEL = "#dropZone QLabel { color:%s; }" % text_primary()
    if active:
        return (
            "#dropZone {"
            f"border:1.5px dashed rgba({r},{g},{b},190);"
            "border-radius:16px;"
            + (f"background:rgba({r},{g},{b},46);" if isDarkTheme()
               else f"background:rgba({r},{g},{b},20);")
            + "}"
            + _DROP_ZONE_LABEL
        )
    return (
        "#dropZone {"
        + (f"border:1.5px dashed rgba(255,255,255,64);"
           if isDarkTheme() else f"border:1.5px dashed rgba(15,40,90,58);")
        + "border-radius:16px; background:transparent; }"
        + _DROP_ZONE_LABEL
    )
