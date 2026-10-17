"""Search failures shared by every fetch mode."""


class SearchError(Exception):
    """A search could not produce results."""


class LoginExpired(SearchError):
    """Splunk no longer accepts the browser's login."""
