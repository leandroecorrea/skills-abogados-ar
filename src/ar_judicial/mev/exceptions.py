"""Custom exceptions for the MEV service."""

from typing import Optional


class MEVError(Exception):
    """Base exception for all MEV-related errors."""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} - Details: {self.details}"
        return self.message


class AuthenticationError(MEVError):
    """Raised when authentication fails."""

    def __init__(self, message: str = "Authentication failed", details: Optional[dict] = None):
        super().__init__(message, details)


class SessionError(MEVError):
    """Raised when there's a session-related error."""

    def __init__(self, message: str = "Session error", details: Optional[dict] = None):
        super().__init__(message, details)


class SearchError(MEVError):
    """Raised when a search operation fails."""

    def __init__(self, message: str = "Search failed", details: Optional[dict] = None):
        super().__init__(message, details)


class ParseError(MEVError):
    """Raised when HTML parsing fails."""

    def __init__(self, message: str = "Failed to parse response", details: Optional[dict] = None):
        super().__init__(message, details)


class NetworkError(MEVError):
    """Raised when a network operation fails."""

    def __init__(self, message: str = "Network error", details: Optional[dict] = None):
        super().__init__(message, details)


class NotFoundError(MEVError):
    """Raised when a requested resource is not found."""

    def __init__(self, message: str = "Resource not found", details: Optional[dict] = None):
        super().__init__(message, details)
