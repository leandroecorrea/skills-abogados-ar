"""
PJN (Poder Judicial de la Nacion) Service Package

A service for interacting with the PJN portal and SCW (Sistema de Consulta Web).

Usage:
    from ar_judicial.pjn import PJNService

    async with PJNService() as service:
        session = await service.authenticate()
        captcha = await service.get_search_captcha()
"""

from .models import (
    Credentials,
    TokenSet,
    UserInfo,
    AuthSession,
    Jurisdiction,
    CaptchaChallenge,
    SearchRequest,
    Expediente,
    ExpedienteList,
    RelacionadosProfile,
    RelacionadosPage,
    PJN_JURISDICTIONS,
)
from .service import PJNService
from .exceptions import (
    PJNError,
    AuthenticationError,
    SessionError,
    TokenError,
    SearchError,
    ParseError,
    NetworkError,
    CaptchaRequiredError,
)

__all__ = [
    # Service
    "PJNService",
    # Models
    "Credentials",
    "TokenSet",
    "UserInfo",
    "AuthSession",
    "Jurisdiction",
    "CaptchaChallenge",
    "SearchRequest",
    "Expediente",
    "ExpedienteList",
    "RelacionadosProfile",
    "RelacionadosPage",
    "PJN_JURISDICTIONS",
    # Exceptions
    "PJNError",
    "AuthenticationError",
    "SessionError",
    "TokenError",
    "SearchError",
    "ParseError",
    "NetworkError",
    "CaptchaRequiredError",
]

__version__ = "0.1.0"
