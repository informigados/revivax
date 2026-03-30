<p align="center">
  <img src="web/static/images/revivax-icon.svg" alt="RevivaX Icon" width="128" />
</p>

<h1 align="center">RevivaX</h1>

<p align="center">
  <strong>Professional read-only data recovery system for Windows</strong>
</p>

<p align="center">
  <a href="https://github.com/informigados/revivax/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-22c55e.svg" alt="License"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.8%2B-3776AB?logo=python&logoColor=white" alt="Python 3.8+"></a>
  <img src="https://img.shields.io/badge/platform-Windows%2010%2F11-0078D6?logo=windows&logoColor=white" alt="Windows 10/11">
  <img src="https://img.shields.io/badge/backend-Flask-000000?logo=flask&logoColor=white" alt="Flask">
  <a href="https://github.com/informigados/revivax/blob/main/SECURITY.md"><img src="https://img.shields.io/badge/security-policy-2563eb" alt="Security Policy"></a>
  <a href="https://github.com/informigados/revivax/blob/main/CONTRIBUTING.md"><img src="https://img.shields.io/badge/contributions-welcome-f59e0b" alt="Contributing"></a>
</p>

## 🧭 Overview

**RevivaX** is a Windows-first file recovery system focused on safe, read-only inspection of drives, folders, and raw disk images. It combines a Flask-based local dashboard with a Python recovery engine that can scan by file signatures, estimate recoverability, inspect SMART health data, and carve matching files to a separate output directory.

The current implementation is designed for **local execution only**. The web interface binds to `127.0.0.1`, the scanner avoids writes to scanned devices, and recovery output is written only to explicitly selected destinations.

The default interface language is **Portuguese (Brazil)**. Active translations are also available for **English**, **Portuguese (Portugal)**, and **Spanish**.

## ✨ Features

- 🔎 **Quick Scan and Deep Scan** for signature-based file discovery.
- 💽 **Raw device access on Windows** for low-level disk inspection when running with administrator privileges.
- 📁 **Folder scan mode** for safer validation, triage, and demo workflows.
- 🧠 **SMART health monitoring** with `smartctl` integration and PowerShell fallback.
- ♻️ **Selective recovery** of discovered files to a separate output directory.
- 📊 **Local dashboard** with scan progress, results, logs, and system status.
- 🌐 **Multilingual interface** with Portuguese (Brazil) as default plus English, Portuguese (Portugal), and Spanish.
- 🔒 **Read-only scanning policy** for the source device.
- 📦 **PyInstaller build** for generating the Windows executable.
- 🧰 **Inno Setup installer script** for packaging the distribution folder into a Windows installer.

## 🚀 Which `.bat` file should you use?

There are now **three** `.bat` files in the repository, each with a clear purpose:

- `RevivaX.bat`
  The **official launcher** for running the system on Windows.
  It:
  - requests administrator elevation when needed,
  - checks whether Python is available,
  - verifies required dependencies,
  - installs only runtime dependencies if missing,
  - starts `main.py`.

- `build.bat`
  The **build script** for packaging RevivaX with PyInstaller.
  It generates `dist\RevivaX\RevivaX.exe`.

- `build-installer.bat`
  The **installer build script** for packaging the PyInstaller output with Inno Setup.
  It generates `dist\installer\RevivaX-Setup.exe`.

## ⚙️ Runtime behavior

When you launch the application through `RevivaX.bat`, the startup flow is:

1. Elevate to administrator if needed.
2. Check Python availability.
3. Verify core dependencies.
4. Install missing runtime dependencies.
5. Start `main.py`.

Inside `main.py`, RevivaX also:

- prepares required directories,
- initializes the recovery and SMART managers,
- checks `smartctl` availability,
- binds to `127.0.0.1`,
- finds the first available port starting from `5000`,
- opens the browser automatically unless disabled.

Persistent restoration of the last scan is **disabled by default** to avoid mixing old state into a new session. If needed for diagnostics, enable it explicitly with:

```bat
set REVIVAX_RESTORE_LAST_JOB=1
python main.py
```

Other supported environment variables:

- `REVIVAX_RESTORE_LAST_JOB`
  Enables automatic restoration of the last saved recovery job when set to `1`, `true`, `yes`, or `on`.
- `REVIVAX_ALLOWED_ORIGINS`
  Optional comma-separated allowlist for local cross-origin API access.
  Example:

```bat
set REVIVAX_ALLOWED_ORIGINS=http://localhost:5000,http://127.0.0.1:5000
python main.py
```

## 🛠️ Requirements

- Windows 10 or Windows 11
- Python 3.8+
- Administrator privileges for physical/raw disk access
- Internet access on first run if dependencies or `smartctl` need to be fetched

Optional:

- `smartmontools` installed globally, although RevivaX can also use a local `tools/smartctl.exe` and has a Windows PowerShell fallback for SMART summaries
- Inno Setup 6, only if you want to generate the Windows installer

## ▶️ Quick Start

### Recommended: Windows launcher

```bat
RevivaX.bat
```

This is the simplest and official way to start the project on Windows.

### Manual start

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Then open the local URL printed by the app, typically:

```text
http://127.0.0.1:5000
```

If port `5000` is already in use, RevivaX automatically selects the next available local port.

## 🧪 Validation

The current project includes smoke coverage for the most important flows:

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

Covered scenarios include:

- raw image file scanning,
- API-based scan flow,
- recovery flow,
- export flow.

## 📦 Packaging

### Build the executable with PyInstaller

```bat
build.bat
```

This uses the official [RevivaX.spec](RevivaX.spec) and produces:

```text
dist\RevivaX\RevivaX.exe
```

Packaging details:

- static and template assets are bundled,
- the local `tools` directory is bundled when present,
- the executable is marked to request **administrator elevation**,
- writable runtime data is redirected to a user-writable application directory when running as a packaged app.

### Build the installer with Inno Setup

```bat
build-installer.bat
```

This requires `ISCC.exe` from **Inno Setup 6** and produces:

```text
dist\installer\RevivaX-Setup.exe
```

The repository includes the installer script in [installer.iss](installer.iss).

## 🏗️ Project Structure

```text
revivax/
├── core/
│   ├── carver.py
│   ├── recovery.py
│   ├── scanner.py
│   ├── smart_monitor.py
│   └── smartctl_setup.py
├── tests/
│   └── test_smoke.py
├── tools/
├── web/
│   ├── app.py
│   ├── static/
│   └── templates/
├── build.bat
├── build-installer.bat
├── installer.iss
├── RevivaX.bat
├── RevivaX.spec
├── main.py
├── requirements.txt
├── requirements-dev.txt
├── CONTRIBUTING.md
├── SECURITY.md
└── README.md
```

## 🔒 Security Notes

- RevivaX binds to **localhost only** (`127.0.0.1`).
- Source scanning is intended to remain **read-only**.
- Recovery output is written to a separate target directory.
- Device and file inputs in the web layer are sanitized before sensitive operations.
- Protected system directories are rejected as recovery destinations.

Please read [SECURITY.md](SECURITY.md) before reporting vulnerabilities.

## 🗺️ Roadmap

- [ ] Replace polling/SSE progress paths with a more unified real-time transport.
- [ ] Add persistent recovery/session storage.
- [ ] Expand file signature coverage.
- [ ] Improve frontend asset packaging to remove runtime CDN dependencies.
- [ ] Add broader automated coverage for SMART, logs, and CSV export.

## 📝 Changelog

### 2026-03-20 (1.0.0)

- Initial release.

## 🤝 Contributing

Contributions are welcome. Before opening a pull request, read [CONTRIBUTING.md](CONTRIBUTING.md) for the expected workflow, testing guidance, and project-specific constraints around read-only recovery behavior.

## 👥 Authors

- [INformigados](https://github.com/informigados)
- [Alex Brito](https://github.com/alexbritodev)

## 📄 License

This project is licensed under the [MIT License](LICENSE).
