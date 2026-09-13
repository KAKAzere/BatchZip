# Changelog

All notable changes to BatchZip are documented in this file.

## [1.0.0-rc2] - 2026-09-13

### Added

- Batch compression for files and folders.
- ZIP and 7Z output formats.
- Queue reordering, pause, resume, completion dialog, and Windows notifications.
- Automatic 7-Zip discovery through PATH, the Windows Registry, and common install locations.
- Reproducible PyInstaller build configuration and Windows version metadata.
- Real progress reporting from 7-Zip with an indeterminate fallback.
- A Cancel button that safely removes the incomplete archive.
- A dedicated folder picker alongside the file picker.

### Fixed

- Existing archives are no longer silently updated; a unique output name is generated.
- Duplicate and invalid queue entries are ignored.
- Completed tasks are not compressed again when Start is clicked a second time.
- File-system and process errors now restore the interface instead of leaving it locked.
- Completion messages now distinguish success, partial failure, and total failure.