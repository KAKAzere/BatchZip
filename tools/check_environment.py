import importlib.metadata as metadata
import re
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = PROJECT_ROOT / "requirements-lock.txt"
_LOCK_ENTRY = re.compile(
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s]+)"
)


def normalize_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass(frozen=True)
class EnvironmentDrift:
    unexpected: tuple
    missing: tuple
    mismatches: tuple

    @property
    def has_drift(self):
        return bool(self.unexpected or self.missing or self.mismatches)


def _normalized_packages(packages):
    return {
        normalize_name(name): (name, version)
        for name, version in packages.items()
    }


def compare_packages(expected_packages, installed_packages):
    expected = _normalized_packages(expected_packages)
    installed = _normalized_packages(installed_packages)

    if "pip" not in expected:
        installed.pop("pip", None)

    unexpected = tuple(
        installed[name]
        for name in sorted(installed.keys() - expected.keys())
    )
    missing = tuple(
        expected[name]
        for name in sorted(expected.keys() - installed.keys())
    )
    mismatches = tuple(
        (
            expected[name][0],
            expected[name][1],
            installed[name][1],
        )
        for name in sorted(expected.keys() & installed.keys())
        if expected[name][1] != installed[name][1]
    )

    return EnvironmentDrift(unexpected, missing, mismatches)


def read_lock(path=LOCK_PATH):
    packages = {}

    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        match = _LOCK_ENTRY.fullmatch(line)

        if match is None:
            raise ValueError(
                f"Unsupported requirements-lock.txt entry on line {line_number}: "
                f"{line!r}"
            )

        name = match.group("name")
        normalized = normalize_name(name)

        if normalized in packages:
            raise ValueError(f"Duplicate package in requirements-lock.txt: {name}")

        packages[normalized] = (name, match.group("version"))

    return {name: version for name, version in packages.values()}


def installed_packages():
    return {
        distribution.metadata["Name"]: distribution.version
        for distribution in metadata.distributions()
    }


def main():
    try:
        expected = read_lock()
    except (OSError, ValueError) as error:
        print(f"Unable to validate requirements-lock.txt: {error}")
        return 1

    drift = compare_packages(expected, installed_packages())

    if not drift.has_drift:
        print("Build environment matches requirements-lock.txt.")
        return 0

    print("Build environment does not match requirements-lock.txt.")

    if drift.unexpected:
        print("\nUnexpected packages:")
        for name, version in drift.unexpected:
            print(f"  {name}=={version}")

    if drift.missing:
        print("\nMissing packages:")
        for name, version in drift.missing:
            print(f"  {name}=={version}")

    if drift.mismatches:
        print("\nVersion mismatches:")
        for name, expected_version, installed_version in drift.mismatches:
            print(f"  {name}")
            print(f"    Expected: {expected_version}")
            print(f"    Installed: {installed_version}")

    print("\nRecreate the build virtual environment before continuing.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
