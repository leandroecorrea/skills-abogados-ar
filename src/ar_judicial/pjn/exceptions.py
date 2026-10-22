"""Custom exceptions for PJN service."""

from typing import Any, Optional


class PJNError(Exception):
    """Base exception for PJN service errors."""

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} - {self.details}"
        return self.message


class AuthenticationError(PJNError):
    """Raised when authentication fails."""

    pass


class SessionError(PJNError):
    """Raised when session management fails."""

    pass


class TokenError(PJNError):
    """Raised when token exchange or refresh fails."""

    pass


class SearchError(PJNError):
    """Raised when search operations fail."""

    pass


class ParseError(PJNError):
    """Raised when parsing responses fails."""

    pass


class NetworkError(PJNError):
    """Raised when network requests fail."""

    pass


class CaptchaRequiredError(PJNError):
    """Raised when a captcha is required to proceed."""

    def __init__(
        self,
        message: str = "Captcha required",
        captcha_html: str = "",
        details: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message, details)
        self.captcha_html = captcha_html
