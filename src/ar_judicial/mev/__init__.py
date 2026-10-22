"""
MEV (Mesa de Entradas Virtual) Service Package

A production-ready Python service for interacting with the SCBA MEV system.

Usage:
    from ar_judicial.mev import MEVService, Credentials, SearchFilesRequest

    async with MEVService() as service:
        # Search for files
        files = await service.search_files(SearchFilesRequest(
            credentials=Credentials(username="user", password="pass"),
            district_code="80",
            court_id="GAM2078",
            case_number="14107"
        ))
"""

from .models import (
    # Credentials
    Credentials,
    # Request models
    SearchFilesRequest,
    SearchFamiliaRequest,
    CourtFileRequest,
    FileOrderRequest,
    # Response models
    CourtFile,
    FullCourtFile,
    FileOrder,
    OrderSummary,
    Attachment,
    CausaContext,
    OrderWithText,
    # Enums
    SearchOption,
    RadioOption,
    CaseType,
    FueroType,
    # Supporting models
    Court,
    District,
)

from .service import MEVService
from .exceptions import (
    MEVError,
    AuthenticationError,
    SessionError,
    SearchError,
    ParseError,
    NetworkError,
    NotFoundError,
)

__all__ = [
    # Service
    "MEVService",
    # Credentials
    "Credentials",
    # Request models
    "SearchFilesRequest",
    "SearchFamiliaRequest",
    "CourtFileRequest",
    "FileOrderRequest",
    # Response models
    "CourtFile",
    "FullCourtFile",
    "FileOrder",
    "OrderSummary",
    "Attachment",
    "CausaContext",
    "OrderWithText",
    # Enums
    "SearchOption",
    "RadioOption",
    "CaseType",
    "FueroType",
    # Supporting models
    "Court",
    "District",
    # Exceptions
    "MEVError",
    "AuthenticationError",
    "SessionError",
    "SearchError",
    "ParseError",
    "NetworkError",
    "NotFoundError",
]

__version__ = "1.0.0"
