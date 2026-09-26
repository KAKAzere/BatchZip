<p align="center">
  <img src="assets/images/banner.svg" alt="BatchZip Banner" width="100%">
</p>

# BatchZip

<p align="center">

<a href="https://github.com/KAKAzere/BatchZip/releases">
<img src="https://img.shields.io/badge/Download-Latest%20Release-blue?style=for-the-badge" alt="Download">
</a>

</p>


BatchZip is a modern batch compression tool for Windows, built with PySide6 and powered by 7-Zip.

It provides a simple graphical workflow for compressing multiple files and folders without relying on command-line operations. BatchZip supports task queues, ZIP and 7Z formats, real-time progress tracking, pause and resume, cancellation, warning handling, and flexible output management.

---

## ✨ Features

- Compress multiple files and folders in one queue.
- Create ZIP or 7Z archives.
- Drag and drop files and folders, or select them with dedicated buttons.
- Reorder queued tasks.
- Show real 7-Zip progress with an indeterminate fallback when progress data is unavailable.
- Pause, resume, or cancel the active compression task.
- Automatically remove incomplete archives after cancellation or unexpected failures.
- Automatically locate 7-Zip through PATH, Windows Registry, and common installation folders.
- Classify 7-Zip errors and provide clear recovery information.
- Handle 7-Zip warnings separately and let users keep or delete incomplete archives.
- Avoid silently overwriting existing archives by generating unique output names.
- Keep BatchZip-managed 7-Zip processes isolated per application instance.
- Automatically terminate the related 7-Zip process if BatchZip is forcibly closed.
- Show completion summaries, detailed failure information, sound notifications, and optional Windows notifications.
- Follow the system light or dark theme.

---

## 🎬 Demo

Switch between **ZIP** and **7Z** formats with a single click.

<p align="center">
  <img src="assets/images/preview/demo.gif" width="88%" alt="BatchZip Format Switch Demo">
</p>

---

## 🖼️ Preview

<p align="center">
  <img src="assets/images/preview/home.png" width="48%" alt="BatchZip Home">
  <img src="assets/images/preview/queue.png" width="48%" alt="BatchZip Queue">
</p>

<p align="center">
  <sub>Left: Home screen · Right: Queue after adding files</sub>
</p>

---

## 📋 Requirements

- Windows 10 or Windows 11
- Python 3.14.x when running from source
- Official release builds use Python 3.14.7 64-bit
- [7-Zip](https://www.7-zip.org/) installed on the computer

---

## 🚀 Run from source

Clone the repository:

```powershell
git clone https://github.com/KAKAzere/BatchZip.git
cd BatchZip
```

Create a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Run:

```powershell
python main.py
```

---

## 📦 Build the Windows executable

Run:

```powershell
.\build.bat
```

The build process uses an isolated virtual environment and locked dependencies to keep release builds consistent.

The build pipeline validates the Python version, dependency environment, version metadata, automated tests, and PyInstaller environment before producing the executable.

The finished executable will be created at:

```text
dist\BatchZip.exe
```

The packaged application still requires 7-Zip to be installed.

BatchZip does not redistribute 7-Zip.

---

## 📁 Project Structure

```text
BatchZip
├── assets
│   ├── icon
│   └── images
│       ├── banner.svg
│       └── preview
│           ├── demo.gif
│           ├── home.png
│           └── queue.png
│
├── core
│   └── Compression logic and application versioning
│
├── ui
│   └── User interface
│
├── tests
│   └── Automated test cases
│
├── tools
│   └── Build and validation utilities
│
├── releases
│   ├── v1.0.0-rc2.md
│   ├── v1.0.0-rc3.md
│   └── v1.0.0-rc4.md
│
├── requirements.txt
├── requirements-dev.txt
├── requirements-lock.txt
├── main.py
└── BatchZip.spec
```

---

## 📂 Output Naming

BatchZip avoids silently overwriting existing archives by generating unique output names.

If:

```text
report.zip
```

already exists, the next archive will be named:

```text
report (2).zip
```

followed by:

```text
report (3).zip
```

and so on.

---

## 🧪 Testing

BatchZip has been tested on:

```text
Windows 11 Home 25H2
Clean Virtual Machine Environment
```

Verified:

- ✅ Standalone EXE startup
- ✅ No Python environment required
- ✅ Missing 7-Zip detection
- ✅ 7-Zip launch failure handling
- ✅ ZIP compression
- ✅ 7Z compression
- ✅ Archive extraction verification
- ✅ Real-time progress reporting
- ✅ Pause and resume
- ✅ Cancellation and incomplete archive cleanup
- ✅ 7-Zip warning handling
- ✅ Keep Archive / Delete Archive warning actions
- ✅ Unicode path compatibility
- ✅ Chinese, Japanese, and special character paths
- ✅ Existing archive name conflict handling
- ✅ Failed compression cleanup
- ✅ Unexpected failure recovery
- ✅ Per-instance 7-Zip process isolation
- ✅ Forced BatchZip termination cleans up its own 7-Zip process
- ✅ Multiple BatchZip instances remain isolated
- ✅ Clean PyInstaller build environment
- ✅ Windows version metadata generation
- ✅ Locked dependency validation
- ✅ Build environment drift detection
- ✅ Clean Windows 11 virtual machine verification

Automated regression tests:

```text
47 tests passing
```

---

## 📝 Release Notes

Detailed release notes for each version are available in the `releases` directory.

---

## 🛠️ Technology Stack

Built with:

- Python
- PySide6
- PySide6-Fluent-Widgets
- 7-Zip
- PyInstaller

---

## 📄 License

## Third-Party Software

BatchZip uses 7-Zip solely as an external compression backend.

BatchZip does not include, bundle, embed, modify, redistribute, or distribute any 7-Zip executable, library, source code, or other 7-Zip files.

BatchZip only invokes a separately installed copy of 7-Zip that is already present on the user's system.

7-Zip must be downloaded and installed separately by the user from the official website:

https://www.7-zip.org/

7-Zip is developed by Igor Pavlov and remains subject to its own copyright and licensing terms.

BatchZip is released under the MIT License.


See [LICENSE](LICENSE) for details.
