from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent


def test_gitignore_keeps_secrets_and_build_output_out():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    for entry in (
        "browser-profile/", "selftest.ok", "config.yaml", "config.yaml.bak", "output/", "dist/",
        "*.log", "*.xlsx", "*.pem", "*.crt", "*.cer", ".env",
    ):
        assert entry in ignored, entry


def test_every_requirement_is_pinned():
    for name in ("requirements.txt", "requirements-dev.txt", "requirements-release.txt"):
        for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "-r")):
                assert "==" in line, f"{name}: {line}"


def test_release_build_installs_the_pinned_lock_file():
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    install = next(s["run"] for s in workflow["jobs"]["build"]["steps"] if s.get("name") == "Install dependencies")
    assert "requirements-release.txt" in install and "pyinstaller" not in install.replace("requirements-release.txt", "")


def test_build_ships_ui_steps_next_to_the_exe():
    assert "ui_steps.yaml" in (ROOT / "build.ps1").read_text(encoding="utf-8")
