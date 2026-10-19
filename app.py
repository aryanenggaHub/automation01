"""Entry point for the packaged app: `--selftest`, otherwise the window."""

import sys

from splunk_seq.paths import app_dir
from splunk_seq.selftest import run_selftest

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(0 if run_selftest(app_dir()) else 1)
    from splunk_seq.gui import main

    main()
