# Contributing to RevivaX

## 🤝 Overview

Thank you for contributing to RevivaX.

This project is a Windows-focused, local-first recovery system. Changes should preserve the core product assumptions:

- source scanning must remain read-only,
- the dashboard must stay local-only by default,
- recovery writes must go to explicit output targets,
- Windows execution remains the primary supported workflow.

## 🧱 Development Setup

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q
```

To run the app manually:

```bash
python main.py
```

To run the Windows launcher:

```bat
RevivaX.bat
```

## 📌 Before You Start

Please check whether your change affects:

- raw disk access,
- scan accuracy,
- recovery output safety,
- SMART data collection,
- Windows startup flow,
- local API behavior,
- packaging with PyInstaller.

If it does, keep the change narrow and validate it carefully.

## ✅ What We Welcome

- bug fixes,
- scan/recovery accuracy improvements,
- safer path validation,
- performance improvements with unchanged recovery semantics,
- test coverage,
- documentation improvements,
- frontend UX improvements that preserve the existing product direction.

## 🚫 What to Avoid

- changing the default binding away from localhost,
- introducing writes to scanned source devices,
- weakening path validation,
- bundling unrelated refactors with bug fixes,
- adding heavy infrastructure that does not match the current local-first design.

## 🧪 Testing Expectations

At minimum, run:

```bash
python -m pytest -q
python -m compileall core web tests main.py
```

If your change touches launch/startup behavior, also verify:

- `RevivaX.bat` still launches correctly,
- dependencies are still detected properly,
- the app still starts on the first available local port,
- the dashboard loads without JavaScript errors.

If your change touches scanning or recovery logic, validate with safe sample files or disk image files before claiming support for physical-drive scenarios.

## 📝 Pull Request Guidance

When opening a PR:

1. Keep the scope focused.
2. Explain the problem being solved.
3. Describe the user-visible effect.
4. List validation steps you ran.
5. Mention any limitations or follow-up work.

Good PRs usually include:

- a clear title,
- a concise summary,
- test evidence,
- screenshots for UI changes when relevant.

## 🔒 Security-Sensitive Changes

If your contribution affects security-sensitive code, read [SECURITY.md](SECURITY.md) first.

Examples:

- file path validation,
- SMART command execution,
- raw drive access,
- recovery destination logic,
- local server binding behavior.

## 🧹 Style Notes

- Prefer small, explicit changes.
- Keep behavior predictable.
- Preserve ASCII unless the file already uses Unicode.
- Match existing code style unless there is a strong reason to improve it.
- Add tests when fixing regressions.

## 📄 License

By contributing, you agree that your contributions will be licensed under the repository's [MIT License](LICENSE).
