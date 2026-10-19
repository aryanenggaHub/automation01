# Ship as a standalone exe with a tkinter UI

The user's company laptop sits behind a TLS-inspecting proxy that breaks `pip install`, and the user is not a Python user, so a "clone and pip install" tool cannot be run there. We therefore package the tool with PyInstaller as a one-folder Windows build (zipped, built by GitHub Actions on version tags and attached to a GitHub Release), drive the already-installed Chrome/Edge instead of downloading Playwright browsers, and give it a tkinter window (standard library, no extra packages, no listening ports) for pasting Input APIs and editing settings. The browser uses a persistent profile folder next to the exe so company SSO (and any required sign-in extension) is set up once rather than on every run.

## Considered Options

- **Single-file exe**: rejected; it unpacks to a temp folder on every start (slow) and is the format antivirus most often flags.
- **Local web UI**: rejected; a process listening on a port is more likely to trip corporate security tools than a native window.
- **Fresh browser profile per run**: rejected; forces SSO/MFA every run and lacks any sign-in extension conditional access may require.
