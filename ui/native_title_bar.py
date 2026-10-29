"""Windows native title bar tinting.

The caption of a window is painted by DWM, not by Qt. It follows the Windows
appearance, not the appearance the application resolved for itself, so an app
set to Dark while Windows is Light keeps a white caption. DWM can be told the
colours explicitly, which is the only way to make the caption obey the app.

The caption is matched to the application page surface, so it reads as part of
the window rather than as a separate frame. These are the same values the page
paints, taken from product_ui.

One function, used by both windows. Every call is best-effort: a platform that
does not support an attribute, or a window without a native handle yet, simply
leaves that attribute untouched. Nothing here can stop a window from opening.
"""

import ctypes
import sys

from ui.product_ui import PAGE_SURFACE_DARK, PAGE_SURFACE_LIGHT

# From dwmapi.h.
DWMWA_USE_IMMERSIVE_DARK_MODE = 20   # Windows 10 20H1 (build 18985) and later
DWMWA_CAPTION_COLOR = 35             # Windows 11 (build 22000) and later
DWMWA_TEXT_COLOR = 36                # Windows 11 (build 22000) and later

# The caption text colour that is legible on each surface.
_CAPTION_TEXT = {True: "#ffffff", False: "#000000"}


def _colorref(hex_colour):
    """Pack '#RRGGBB' into a COLORREF, which is 0x00BBGGRR."""
    value = hex_colour.lstrip("#")
    red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return (blue << 16) | (green << 8) | red


def _set(dwm, handle, attribute, value):
    """Set one unsigned DWM attribute. Returns whether it was accepted."""
    data = ctypes.c_uint(value)
    result = dwm.DwmSetWindowAttribute(
        ctypes.c_void_p(handle),
        ctypes.c_uint(attribute),
        ctypes.byref(data),
        ctypes.sizeof(data),
    )
    return result == 0


def apply_title_bar_theme(widget, dark):
    """Match `widget`'s native caption to the application theme.

    Called from the theme refresh path, so it must stay cheap and must never
    raise: a window that cannot be tinted still opens and works.
    """
    if sys.platform != "win32":
        return False
    try:
        handle = int(widget.winId())
    except Exception:
        return False
    if not handle:
        return False
    try:
        dwm = ctypes.windll.dwmapi
    except Exception:
        return False

    surface = PAGE_SURFACE_DARK if dark else PAGE_SURFACE_LIGHT
    applied = False
    try:
        # Older builds only understand the immersive flag, and it is still what
        # asks DWM for dark caption buttons.
        if _set(dwm, handle, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0):
            applied = True
        # The explicit colours are what actually force the caption while Windows
        # itself is in the opposite appearance.
        if _set(dwm, handle, DWMWA_CAPTION_COLOR, _colorref(surface)):
            applied = True
        if _set(dwm, handle, DWMWA_TEXT_COLOR,
                _colorref(_CAPTION_TEXT[dark])):
            applied = True
    except Exception:
        return applied
    return applied
