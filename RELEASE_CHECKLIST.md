# BatchZip v1.0.0-rc2 Release Checklist

## Before building

- [ ] Install the latest stable 7-Zip release.
- [ ] Run `python -m unittest discover -v`.
- [ ] Test files, folders, Unicode paths, duplicate names, ZIP, and 7Z.
- [ ] Test real progress, pause, resume, cancel, window closing during compression, and an invalid output path.
- [ ] Confirm that cancelling removes the incomplete archive and leaves queued tasks waiting.
- [ ] Confirm that Windows notifications and **Open Folder** work.

## Build

- [ ] Run `build.bat` on Windows.
- [ ] Start `dist\BatchZip.exe` on a computer without Python installed.
- [ ] Confirm the EXE and taskbar icons appear correctly.
- [ ] Scan the final EXE with Microsoft Defender.

## Git and GitHub

- [ ] Run `git status` and review every changed or untracked file.
- [ ] Run `git add .`.
- [ ] Commit the v1.0.0-rc2 source.
- [ ] Push the commit to GitHub.
- [ ] Create the `v1.0.0-rc2` tag and GitHub Release.
- [ ] Upload `BatchZip.exe` as the release asset.
- [ ] Copy the v1.0.0-rc2 notes from `CHANGELOG.md` into the release description.

Do not upload a manually zipped working directory containing `.git`, `.venv`, `__pycache__`, `build`, or `dist`.