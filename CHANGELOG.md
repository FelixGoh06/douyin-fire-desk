# Changelog

## v1.0.2 - 2026-08-15

- Moved administrator password management to a consistent sidebar action and modal dialog.
- Added automatic reopening of the password dialog after validation errors.

## v1.0.1 - 2026-08-15

- Added the System-page administrator password change flow with current-password verification, CSRF protection, format validation, automatic logout, and controlled service restart.
- Added a narrowly scoped root helper and sudo rule installed by `install.sh`; the web process cannot write the full server environment file directly.

## v1.0.0 - 2026-08-15

- First open-source release of Douyin Fire Desk.
- Added account, Cookie, task, target friend, scheduler, real-time run log, and batch reporting workflows.
- Added optional OpenClaw Skill, notification timer, Cookie health reporting, and one-command integration setup.
- Added Debian/Ubuntu installer, diagnostics, uninstall script, GitHub Actions test workflow, and full Chinese documentation.
