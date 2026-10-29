# Changelog

All notable changes to BatchZip are documented in this file.



## [1.0.0-rc5] - 2026-10-02

### Added
- Added an authoritative task-queue model as the single source of truth for task membership, ordering, and identity.
- Added a task-queue delegate that paints task rows directly without constructing a widget per row.
- Added a task-queue runtime controller connecting the production window to the queue model.
- Added List and Grid layouts that render one shared authoritative task order.
- Added queue interaction locking for the duration of a compression session.
- Added single-entry compression-session state seams for the active and paused states.
- Added rollback and recovery when the background compression worker fails to start.

### Changed
- Migrated the production task queue to the model/view/delegate architecture.
- Reordering now moves rows through the model, preserving task identity without a model reset.
- Removed the legacy per-item task card production path (`ui/task_card.py`).
- Removed the orphaned `Task.compact` field.
- Replaced the drop-zone queue-count API with a prompt-reset API.

### Fixed
- Fixed a new compression session being displayed as `Paused` after pause, cancel, and restart.
- Fixed a worker-start failure leaving the session active, the queue locked, and the controls disabled.
- Fixed queue-lock and pause presentation being updated independently of the compression-session state.

### Testing
- Expanded the automated test suite to 167 tests.
- Verified the real production path end to end on Windows 11 with a real 7-Zip 26.03 installation.
- Verified ZIP, 7Z, files, folders, Unicode and space-containing paths, nested folder trees, empty files and empty folders, and existing archive name conflicts.
- Verified pause and resume of a 256 MiB compression.
- Verified cancellation, partial archive cleanup, and cancellation followed by a new session.
- Verified warning handling, Keep Archive, Delete Archive, and failed task handling.
- Verified archive integrity by testing each archive, extracting it, and comparing SHA-256 hashes.
- Verified the packaged single-file executable: launch outside the repository, launch from non-ASCII paths, real ZIP and 7Z compression, pause, resume, cancellation, completion dialog, 7-Zip child process, extraction cleanup, and clean process exit.




## [1.0.0-rc4] - 2026-09-22

### Added
- Added per-instance Windows Job Object management for 7-Zip processes, ensuring child compression processes terminate if BatchZip is forcibly closed.
- Added detailed 7-Zip exit-code handling, including a dedicated warning state for partial compression results.
- Added Keep Archive / Delete Archive actions for archives completed with warnings.
- Added a single source of truth for application versioning through `core/version.py`.
- Added reproducible build dependency locking with `requirements-lock.txt`.
- Added build environment drift detection to ensure the active `.venv` exactly matches the locked dependencies.
- Added automatic Windows version-resource generation from the application version.

### Changed
- Improved warning dialogs with clearer English-only diagnostics, affected-file reporting, and more consistent layout.
- Improved completion summaries to distinguish successful, warning, and failed tasks.
- Updated the build process to use Python 3.14.7 64-bit, an isolated `.venv`, and pinned dependencies.
- Updated the release checklist to use reusable version placeholders instead of hard-coded release numbers.
- Removed the hard-coded current release candidate from the README.

### Fixed
- Fixed 7-Zip processes remaining alive after BatchZip was forcibly terminated.
- Fixed partial archive cleanup errors being silently ignored.
- Fixed localized 7-Zip output decoding by forcing UTF-8 console output.
- Fixed incorrect or ambiguous completion messages when tasks completed with warnings.
- Fixed PyInstaller builds being contaminated by external DLL search paths.
- Prevented external `libheif`, Poppler, JXRLib, and other native runtime DLLs from leaking into BatchZip builds by isolating the build PATH.

### Testing
- Expanded the automated test suite to 47 tests.
- Verified ZIP and 7Z compression, pause/resume, cancellation, warning handling, archive keep/delete behavior, Unicode paths, and multi-instance process isolation.
- Verified the final PyInstaller build in a clean Windows 11 environment.




## [1.0.0-rc3] - 2026-09-21

### Added

- Detailed failure explanations with user-friendly error messages.
- Failure details view in the completion dialog.
- Additional regression tests for compression failure scenarios.

### Improved

- Redesigned error handling across compression and UI layers.
- Improved 7-Zip error classification and recovery guidance.
- Improved failed archive cleanup to prevent incomplete archives from being left behind.
- Improved Windows subprocess handling to prevent unnecessary console window flashes.
- Refined the completion dialog layout for clearer failure reporting.

### Fixed

- Incorrect error messages caused by ambiguous exception handling.
- Partial archives remaining after unexpected compression failures.
- 7-Zip detection causing a brief console window flash on Windows.
- Inconsistent failure states during abnormal compression termination.




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


## [1.0.0-rc3] - 2026-09-21

### Added

- Detailed failure explanations with user-friendly error messages.
- Failure details view in the completion dialog.
- Additional regression tests for compression failure scenarios.

### Improved

- Redesigned error handling across compression and UI layers.
- Improved 7-Zip error classification and recovery guidance.
- Improved failed archive cleanup to prevent incomplete archives from being left behind.
- Improved Windows subprocess handling to prevent unnecessary console window flashes.
- Refined the completion dialog layout for clearer failure reporting.

### Fixed

- Incorrect error messages caused by ambiguous exception handling.
- Partial archives remaining after unexpected compression failures.
- 7-Zip detection causing a brief console window flash on Windows.
- Inconsistent failure states during abnormal compression termination.