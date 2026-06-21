class RetryableError(Exception):
    """Provider is temporarily unavailable. FallbackProvider will try the next provider."""


class FatalError(Exception):
    """Request is structurally invalid or provider is not implemented. Do not retry."""
