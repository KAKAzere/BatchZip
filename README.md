<p align="center">
  <img src="assets/images/banner.svg" alt="BatchZip Banner" width="100%">
</p>

# BatchZip

BatchZip is a modern batch compression tool for Windows, built with PySide6 and 7-Zip.

It lets you queue multiple files and folders, choose ZIP or 7Z formats, reorder tasks, pause and resume compression, and select a shared output folder.

---

## ✨ Features

- Compress multiple files and folders in one queue.
- Create ZIP or 7Z archives.
- Drag and drop files and folders, or select them with dedicated buttons.
- Reorder queued tasks.
- Show real 7-Zip progress, with an indeterminate fallback when unavailable.
- Pause, resume, or cancel the active 7-Zip process.
- Remove incomplete archives after cancellation.
- Automatically locate 7-Zip through PATH, Windows Registry, and common installation folders.
- Avoid overwriting existing archives by generating unique output names.
- Show completion details, sound notifications, and optional Windows notifications.
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
- Python 3.12 or later when running from source
- [7-Zip](https://www.7-zip.org/) installed on the computer

---

## 🚀 Run from source

Clone the repository:

```powershell
git clone https://github.com/kakazere/BatchZip.git
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
│   └── Compression logic
│
├── ui
│   └── User interface
│
├── tests
│   └── Test cases
│
├── tools
│   └── Utility scripts
│
├── main.py
└── BatchZip.spec
```

---

## 📂 Output Naming

BatchZip never silently overwrites existing archives.

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
- ✅ ZIP compression
- ✅ 7Z compression
- ✅ Archive extraction verification
- ✅ Unicode path compatibility
- ✅ Chinese, Japanese, and special character paths

---

## 🛠️ Technology Stack

Built with:

- Python
- PySide6
- PySide6-Fluent-Widgets
- 7-Zip

---

## 📄 License

BatchZip is released under the MIT License.

See [LICENSE](LICENSE) for details.
