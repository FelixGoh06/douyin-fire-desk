# Changelog

## v1.0.13

- After WeChat login, the setup now waits up to 90 seconds for a receiver message and retries automatic pairing approval instead of checking only once.
- Re-running the installer now detects an already connected WeChat channel and skips the QR-login flow, preventing duplicate scans during recovery or upgrades.

## v1.0.12

- Made OpenClaw Gateway startup idempotent: the setup now installs the user service when missing, waits for one healthy startup, and performs one controlled reload after WeChat login instead of issuing overlapping restarts during startup migrations.

## v1.0.11

- Fixed interactive OpenClaw setup after the one-line `curl | sudo bash` command: the bootstrapper now reconnects the installer to `/dev/tty`, so model selection receives arrow-key and Enter input instead of exiting with an unsettled top-level-await warning.

## v1.0.10

- The bundled OpenClaw onboarding now selects the recommended QuickStart flow automatically before opening model-provider configuration.

## v1.0.9

- The automatic OpenClaw flow now acknowledges the CLI's safety notice before launching the model wizard, leaving model setup and WeChat pairing as the only user interactions.

## v1.0.8

- Updated the bundled model onboarding command for the current OpenClaw CLI, which removed the obsolete `--tui` and `--agent-name` flags.

## v1.0.7

- Prevented the official OpenClaw installer from launching its unrestricted onboarding; the bundled installer now owns the guided flow and only opens the model configuration before it automatically configures the Skill, WeChat plugin, Gateway, and reporting runtime.

## v1.0.6

- Installer and credential recovery now prefer the Tencent Cloud public-IP metadata endpoint, then public IP services, so the displayed Web address does not incorrectly use a `10.x` private address on Tencent Cloud.

## v1.0.5

- Added a Gitee-first `bootstrap.sh` so a clean mainland server can start with one command.
- Made `install.sh --with-openclaw` install OpenClaw, the bundled Skill, Tencent WeChat plugin, and the report runtime automatically.
- Reduced first-run OpenClaw interaction to model configuration and WeChat account/recipient pairing.
- Added a container fallback for the OpenClaw Gateway and notification loop when systemd is unavailable.
- Added `show-admin-credentials.sh` for securely displaying the existing administrator password and public URL hint again.
- Expanded installation and troubleshooting documentation with public-port, Docker, China-network, WeChat pairing, and password-recovery guidance.

## v1.0.4 - 2026-08-16

- Added a Gitee-first installation path for mainland China servers and a GitHub Actions workflow for mirror synchronization.

## v1.0.3 - 2026-08-16

- Replaced the installation-document placeholder with the live GitHub clone URL.

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
