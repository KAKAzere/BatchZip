import unittest

from tools.check_environment import compare_packages


class EnvironmentDriftTests(unittest.TestCase):
    def test_matching_environment_succeeds(self):
        drift = compare_packages(
            {"psutil": "7.2.2"},
            {"psutil": "7.2.2"},
        )

        self.assertFalse(drift.has_drift)

    def test_unexpected_package_fails(self):
        drift = compare_packages(
            {"psutil": "7.2.2"},
            {"psutil": "7.2.2", "Pillow": "12.3.0"},
        )

        self.assertEqual(drift.unexpected, (("Pillow", "12.3.0"),))
        self.assertTrue(drift.has_drift)

    def test_missing_package_fails(self):
        drift = compare_packages(
            {"psutil": "7.2.2"},
            {},
        )

        self.assertEqual(drift.missing, (("psutil", "7.2.2"),))
        self.assertTrue(drift.has_drift)

    def test_version_mismatch_fails(self):
        drift = compare_packages(
            {"PyInstaller": "6.22.3"},
            {"PyInstaller": "6.23.0"},
        )

        self.assertEqual(
            drift.mismatches,
            (("PyInstaller", "6.22.3", "6.23.0"),),
        )
        self.assertTrue(drift.has_drift)

    def test_package_names_are_normalized(self):
        drift = compare_packages(
            {"PySide6-Addons": "6.11.2"},
            {"pyside6_addons": "6.11.2"},
        )

        self.assertFalse(drift.has_drift)

    def test_pip_is_ignored_when_not_in_lock(self):
        drift = compare_packages(
            {"psutil": "7.2.2"},
            {"psutil": "7.2.2", "pip": "26.2.1"},
        )

        self.assertFalse(drift.has_drift)


if __name__ == "__main__":
    unittest.main()
