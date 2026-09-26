import re


APP_VERSION = "1.0.0-rc4"

_VERSION_PATTERN = re.compile(
    r"(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-rc(?P<rc>\d+))?"
)
_MAX_WINDOWS_COMPONENT = 65535
_FINAL_BUILD = 1000


def windows_version(version):
    match = _VERSION_PATTERN.fullmatch(version)

    if match is None:
        raise ValueError(
            "Version must use major.minor.patch or major.minor.patch-rcN."
        )

    major, minor, patch = (
        int(match.group(name)) for name in ("major", "minor", "patch")
    )

    if any(
        component > _MAX_WINDOWS_COMPONENT
        for component in (major, minor, patch)
    ):
        raise ValueError("Windows version components must not exceed 65535.")

    rc_text = match.group("rc")
    build = _FINAL_BUILD if rc_text is None else int(rc_text)

    if rc_text is not None and not 1 <= build < _FINAL_BUILD:
        raise ValueError("Release candidate number must be between 1 and 999.")

    return major, minor, patch, build


WINDOWS_VERSION = windows_version(APP_VERSION)
