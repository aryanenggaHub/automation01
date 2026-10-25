class FakeBrowser:
    """Stands in for BrowserSession: no Playwright, configurable start failure."""

    start_error = None

    def __init__(self, cfg, should_stop=lambda: False, log=print):
        self.page = None

    def __enter__(self):
        if self.start_error is not None:
            raise self.start_error
        return self

    def __exit__(self, *exc):
        return False
