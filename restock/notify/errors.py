class NotifyError(RuntimeError):
    """Delivery failed; the dispatcher retries with backoff."""


class RetryLater(NotifyError):
    """The service asked us to slow down (HTTP 429)."""

    def __init__(self, seconds: float) -> None:
        super().__init__(f"rate limited, retry in {seconds:.0f}s")
        self.seconds = seconds
