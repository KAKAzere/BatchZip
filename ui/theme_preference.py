"""Where BatchZip remembers the appearance preference.

One value, one file, in the per-user application data directory. There is no
settings framework here on purpose: the application has exactly one persisted
preference so far, and a manager or service layer would be more machinery than
the value is worth.

Reading never raises. A missing file, unreadable file, malformed JSON, unknown
value or a theme name this build does not know all fall back to
``Theme.AUTO``, which means "follow Windows" - the same behaviour the product
had before the preference existed.
"""

import json
import os
from pathlib import Path

from qfluentwidgets import Theme

APP_DIR_NAME = "BatchZip"
FILE_NAME = "settings.json"
KEY = "themeMode"

# Stored as stable lowercase tokens rather than enum reprs, so the file stays
# readable and does not depend on how the enum happens to serialise.
_TOKENS = {
    "system": Theme.AUTO,
    "light": Theme.LIGHT,
    "dark": Theme.DARK,
}
_NAMES = {mode: token for token, mode in _TOKENS.items()}


def theme_for_token(token):
    """The Theme for a stored token, or Theme.AUTO when it is unknown."""
    return _TOKENS.get(token, Theme.AUTO)


def token_for_theme(mode):
    """The stored token for a Theme, or 'system' when it is unknown."""
    return _NAMES.get(mode, 'system')


def config_path():
    """The settings file path, under %LOCALAPPDATA%\\BatchZip.

    Falls back to the home directory if LOCALAPPDATA is somehow unset, so the
    preference still has somewhere to live instead of raising at import time.
    """
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / APP_DIR_NAME / FILE_NAME


def load_theme_mode():
    """The saved appearance mode, or Theme.AUTO when anything is wrong."""
    try:
        with open(config_path(), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return Theme.AUTO
    if not isinstance(data, dict):
        return Theme.AUTO
    token = data.get(KEY)
    if not isinstance(token, str):
        return Theme.AUTO
    return _TOKENS.get(token.strip().lower(), Theme.AUTO)


def save_theme_mode(mode):
    """Persist the appearance mode. Returns whether the write succeeded.

    Failures are reported rather than raised: a preference that cannot be saved
    must never stop the application from running.
    """
    token = _NAMES.get(mode)
    if token is None:
        return False
    path = config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write beside the target and replace, so an interrupted write cannot
        # leave a half-written settings file behind.
        temporary = path.with_suffix(".tmp")
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump({KEY: token}, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
        return True
    except OSError:
        return False
