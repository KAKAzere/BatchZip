import tempfile
import unittest
from pathlib import Path

from core.version import APP_VERSION, windows_version
from tools.generate_version_info import generate_version_info, render_version_info


class VersionTests(unittest.TestCase):
    def test_supported_versions_map_to_windows_versions(self):
        cases = (
            ("1.0.0-rc3", (1, 0, 0, 3)),
            ("1.0.0-rc1", (1, 0, 0, 1)),
            ("1.0.0", (1, 0, 0, 1000)),
            ("1.0.1", (1, 0, 1, 1000)),
            ("1.1.0-rc2", (1, 1, 0, 2)),
        )

        for version, expected in cases:
            with self.subTest(version=version):
                self.assertEqual(windows_version(version), expected)

    def test_invalid_versions_are_rejected(self):
        invalid_versions = (
            "1.0",
            "v1.0.0",
            "1.0.0-beta",
            "abc",
            "1.0.0-rc0",
            "1.0.0-rc1000",
            "65536.0.0",
        )

        for version in invalid_versions:
            with self.subTest(version=version):
                with self.assertRaises(ValueError):
                    windows_version(version)

    def test_version_resource_is_derived_from_application_version(self):
        resource = render_version_info(APP_VERSION)
        numeric_version = windows_version(APP_VERSION)

        self.assertIn(f"filevers={numeric_version}", resource)
        self.assertIn(f"prodvers={numeric_version}", resource)
        self.assertIn(
            f"StringStruct(u'FileVersion', u'{APP_VERSION}')",
            resource,
        )
        self.assertIn(
            f"StringStruct(u'ProductVersion', u'{APP_VERSION}')",
            resource,
        )
        self.assertIn("StringStruct(u'CompanyName', u'KAKAzere')", resource)
        self.assertIn(
            "StringStruct(u'OriginalFilename', u'BatchZip.exe')",
            resource,
        )

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "version_info.txt"
            generate_version_info(output)
            self.assertEqual(output.read_text(encoding="utf-8"), resource)

        repository_resource = (
            Path(__file__).resolve().parents[1] / "version_info.txt"
        )
        self.assertEqual(
            repository_resource.read_text(encoding="utf-8"),
            resource,
        )


if __name__ == "__main__":
    unittest.main()
