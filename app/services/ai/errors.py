"""MYOS error types every adapter maps provider failures into."""


class ModelError(Exception):
    kind = "unknown"
    retryable = True


class Unavailable(ModelError):
    kind = "unavailable"


class Timeout(ModelError):
    kind = "timeout"


class RateLimited(ModelError):
    kind = "rate_limited"


class Quota(ModelError):
    kind = "quota"
    retryable = False


class Auth(ModelError):
    kind = "auth"
    retryable = False


class Config(ModelError):
    kind = "config"
    retryable = False


class InvalidOutput(ModelError):
    kind = "invalid_output"


class NotEligible(ModelError):
    """No provider is eligible for this clinic, task and data class. Never retried elsewhere."""
    kind = "not_eligible"
    retryable = False
