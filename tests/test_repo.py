from pathlib import Path


def test_gitignore_keeps_secrets_and_build_output_out():
    ignored = Path(".gitignore").read_text(encoding="utf-8").split()
    for entry in ("browser-profile/", "selftest.ok", "config.yaml", "output/", "dist/"):
        assert entry in ignored
