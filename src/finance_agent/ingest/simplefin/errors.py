"""Errors from the live SimpleFIN connector.

Every message is a fixed, safe string: it never contains the setup token, the
access URL or its credentials, so an exception may be logged or shown as-is
(invariant 8). ``retryable`` says whether trying again later could succeed (the
bank was down or slow) rather than a permanent problem (a spent token, revoked
access).
"""


class SimpleFinError(Exception):
    """Base class. ``message`` is safe to show the user; ``retryable`` guides sync."""

    retryable: bool = False

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class MalformedSetupToken(SimpleFinError):
    """The setup token is not base64 that decodes to a URL."""


class UnsafeClaimUrl(SimpleFinError):
    """The claim URL is not https; credentials must never cross plain HTTP."""


class TokenAlreadyClaimed(SimpleFinError):
    """The bank rejected the claim: the token was already spent."""


class ClaimFailed(SimpleFinError):
    """The claim request failed for another reason."""


class AccessRevoked(SimpleFinError):
    """The bank rejected the access URL (revoked or invalid); the user must reconnect."""


class BankUnavailable(SimpleFinError):
    """The bank could not be reached or returned a server error. Worth retrying."""

    retryable = True


class ResponseTooLarge(SimpleFinError):
    """The response exceeded the size cap and was refused."""


class DestinationNotAllowed(SimpleFinError):
    """A request to a host other than the pinned bank host was refused."""
