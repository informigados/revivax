# Security Policy

## 🔐 Supported Scope

RevivaX is a **local-only Windows application** for read-only scanning, recovery analysis, and selective file carving.

Security-sensitive areas include:

- raw disk access,
- local web API routes,
- recovery output path handling,
- SMART command execution,
- packaged executable behavior,
- any code path that could cause writes to the scanned source device.

## ✅ Supported Versions

The project currently supports security fixes for the latest state of the `main` branch and the latest packaged release, when available.

Older snapshots, forks, or private modifications are not guaranteed to receive fixes.

## 📣 Reporting a Vulnerability

If you believe you found a security issue:

1. Do **not** publish exploit details in a public issue.
2. Prefer a private GitHub security report if the repository has private reporting enabled.
3. If private reporting is not available, contact the maintainers through their GitHub profiles and include:
   - a clear description of the issue,
   - affected files or routes,
   - reproduction steps,
   - impact assessment,
   - suggested mitigation if available.

Maintainers:

- [INformigados](https://github.com/informigados)
- [Alex Brito](https://github.com/AlexBritoDEV)

## 🧭 What to Include

Please include as much of the following as possible:

- affected version or commit,
- Windows version,
- whether the issue occurs in source mode or packaged `.exe` mode,
- whether administrator privileges are required,
- exact request payload or local input used,
- logs or screenshots if relevant,
- whether the issue impacts confidentiality, integrity, or availability.

## 🚫 Please Avoid Public Disclosure For

- path traversal or arbitrary write issues,
- unsafe recovery destination handling,
- localhost exposure or network binding regressions,
- command injection,
- raw device write risks,
- packaged executable privilege escalation concerns.

## 🛡️ Current Security Design

RevivaX currently relies on the following security assumptions and controls:

- the web interface binds to `127.0.0.1`,
- source disk scanning is intended to be read-only,
- output paths are validated before recovery writes,
- device identifiers are sanitized in SMART endpoints,
- protected system directories are rejected as recovery targets.

## ⚠️ Out of Scope

The following are generally out of scope unless they clearly lead to a real security impact:

- cosmetic UI bugs,
- missing hardening for unsupported operating systems,
- local crashes without privilege or data boundary impact,
- issues that require manually modifying the source code before execution.
