"""MYOS error types every adapter maps provider failures into."""


class ModelError(Exception):
    kind = "unknown"
    retryable = True
    # Provider's own request id (e.g. OpenAI x-request-id); safe to log, contains no text.
    provider_request_id = None


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


class Access(ModelError):
    """Key is valid but the project/org cannot use this model (403 permission, 404 model_not_found)."""
    kind = "access"
    retryable = False


class Config(ModelError):
    kind = "config"
    retryable = False


class InvalidOutput(ModelError):
    """The provider answered but the response could not be parsed (empty, malformed, schema mismatch)."""
    kind = "parsing"


class NotEligible(ModelError):
    """No provider is eligible for this clinic, task and data class. Never retried elsewhere."""
    kind = "not_eligible"
    retryable = False
