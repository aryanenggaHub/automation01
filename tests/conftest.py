class FakeBrowser:
    """Stands in for BrowserSession: no Playwright, configurable login and start failure."""

    logged_in = True
    start_error = None

    def __init__(self, cfg, should_stop=lambda: False, log=print):
        self.page = None

    def __enter__(self):
        if self.start_error is not None:
            raise self.start_error
        return self

    def __exit__(self, *exc):
        return False

    def wait_for_login(self):
        return self.logged_in

    def post(self, url, form, headers, timeout_s):
        return 200, "application/json", ""

    def cookies(self):
        return []
