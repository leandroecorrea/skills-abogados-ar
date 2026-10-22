"""Domain models for the MEV service.

This module contains all request and response models used by the MEV service.
Models are organized into three categories:
1. Enums - Type classifications
2. Request models - Input for service methods
3. Response models - Output from service methods
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional


# =============================================================================
# ENUMS
# =============================================================================


class SearchOption(Enum):
    """Search option types for MEV."""

    BY_NUMBER = "1"  # Search by file number
    BY_CAPTION = "2"  # Search by case caption (caratula)


class RadioOption(Enum):
    """Radio button options for search type."""

    BY_CAPTION = "xCa"  # Por Caratula
    BY_CASE_NUMBER = "xNc"  # Por Nro. de Causa
    BY_RECEIVED_NUMBER = "xNr"  # Por Nro. de Receptoria
    BY_INTERNAL_NUMBER = "xNi"  # Por Nro. Interno


class CaseType(Enum):
    """Case type options (TipoCausa)."""

    CIVIL = "Ac"  # Civil actions
    COMMERCIAL = "Am"  # Commercial matters
    ALL = ""  # All types


class FueroType(Enum):
    """Fuero type for MEV district context (TipoF parameter in POSLoguin).

    NOTE: This enum is specific to MEV API calls. MEV only differentiates between
    civil/comercial (default) and familia. Other fueros like laboral, contencioso_administrativo,
    and penal use the civil/comercial endpoint but are tracked separately in the
    juzgados.fuero database column for deadline calculations and document generation.
    """

    CIVIL_COMERCIAL = ""  # No TipoF parameter (default behavior)
    FAMILIA = "FF"  # Fuero de Familia


# =============================================================================
# CREDENTIAL MODEL
# =============================================================================


@dataclass(frozen=True)
class Credentials:
    """
    User credentials for MEV authentication.

    This is immutable (frozen) to prevent accidental modification.
    """

    username: str
    password: str


# =============================================================================
# SUPPORTING MODELS
# =============================================================================


@dataclass
class Court:
    """A court within a judicial district."""

    query_code: str  # QueryCode - used in JuzgadoElegido (e.g., "GAM2078")
    fullname: str  # Display name

    @classmethod
    def from_dict(cls, data: dict) -> "Court":
        return cls(
            query_code=data.get("QueryCode", "").strip(),
            fullname=data.get("Fullname", "").strip(),
        )

    @classmethod
    def from_scraped_dict(cls, data: dict) -> "Court":
        """Create Court from scraped_courts.json format."""
        return cls(
            query_code=data.get("code", "").strip(),
            fullname=data.get("name", "").strip(),
        )


@dataclass
class District:
    """A judicial district with its courts."""

    creation_code: str  # CreationCode - used for login (e.g., "LP")
    tracking_code: str  # TrackingCode / id - used for POSLoguin (e.g., "80")
    district_name: str  # DistrictName / titulo
    courts: list[Court] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "District":
        courts = [Court.from_dict(c) for c in data.get("Courts", [])]
        return cls(
            creation_code=data.get("CreationCode", ""),
            tracking_code=data.get("TrackingCode", ""),
            district_name=data.get("DistrictName", ""),
            courts=courts,
        )

    @classmethod
    def from_scraped_dict(cls, data: dict) -> "District":
        """Create District from scraped_courts.json format."""
        courts = [Court.from_scraped_dict(c) for c in data.get("juzgados", [])]
        return cls(
            creation_code="",  # Not available in scraped data
            tracking_code=data.get("id", ""),
            district_name=data.get("titulo", ""),
            courts=courts,
        )

    def find_court(self, name_contains: str) -> Court | None:
        """Find a court by partial name match."""
        name_lower = name_contains.lower()
        for court in self.courts:
            if name_lower in court.fullname.lower():
                return court
        return None


# =============================================================================
# REQUEST MODELS
# =============================================================================


@dataclass
class SearchFilesRequest:
    """
    Request to search for court files.

    All service methods require credentials and district_code because
    each request performs: Login -> Set POS Login -> Action
    """

    credentials: Credentials
    district_code: str  # District tracking code (e.g., "80" for Avellaneda)
    court_id: str  # JuzgadoElegido (e.g., "GAM2078")

    # Search type configuration
    search_option: SearchOption = SearchOption.BY_NUMBER
    radio_option: RadioOption = RadioOption.BY_CASE_NUMBER
    case_type: CaseType = CaseType.CIVIL

    # Search terms (use the one matching the search option/radio option)
    case_number: str = ""  # NCausa - for BY_NUMBER + BY_CASE_NUMBER
    case_caption: str = ""  # caratula - for BY_CAPTION
    internal_number: str = ""  # NInterno - for BY_NUMBER + BY_INTERNAL_NUMBER
    received_number: str = ""  # For BY_NUMBER + BY_RECEIVED_NUMBER

    # Date range (optional, defaults to last 2 days)
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None

    # Pagination
    result_set: str = ""  # Set
    news_set: str = ""  # SetNovedades

    def to_form_data(self) -> dict[str, str]:
        """Convert to form data dictionary for POST request."""
        now = datetime.now()
        from_date = self.date_from or (now - timedelta(days=2))
        to_date = self.date_to or now

        def format_date(dt: datetime) -> str:
            return f"{dt.month}/{dt.day}/{dt.year}"

        # When searching by caption, use xCa radio option
        if self.search_option == SearchOption.BY_CAPTION:
            radio_value = RadioOption.BY_CAPTION.value
        else:
            radio_value = self.radio_option.value

        return {
            "OpcionBusqueda": self.search_option.value,
            "busca": "",
            "JuzgadoElegido": self.court_id,
            "caratula": self.case_caption,
            "NCausa": self.case_number,
            "radio": radio_value,
            "NInterno": self.internal_number,
            "Set": self.result_set,
            "Desde": format_date(from_date),
            "Hasta": format_date(to_date),
            "SetNovedades": self.news_set,
            "TipoCausa": self.case_type.value,
            "Buscar": "Buscar",
        }


@dataclass
class CourtFileRequest:
    """
    Request to get or download a specific court file.

    Used for:
    - get_file(): Gets file summary from procesales.asp
    - download_file(): Downloads all orders for a file

    URL pattern:
    - procesales.asp?nidCausa={case_id}&pidJuzgado={court_id}    
    """

    credentials: Credentials
    district_code: str  # District tracking code (e.g., "80")
    court_id: str  # pidJuzgado (e.g., "GAM2078")
    case_id: str  # nidCausa (e.g., "1281688")
    fuero: str = ""


@dataclass
class FileOrderRequest:
    """
    Request to read a specific court order.

    URL pattern: proveido.asp?pidJuzgado={court_id}&sCodi={order_code}&nPosi={position}&sFile={file_type}&MT=
    """

    credentials: Credentials
    district_code: str  # District tracking code (e.g., "80")
    court_id: str  # pidJuzgado (e.g., "GAM2078")
    order_code: str  # sCodi - Order code (e.g., "1933063")
    position: str  # nPosi - Position (e.g., "27606093")
    file_type: str = "a"  # sFile - File type marker


@dataclass
class SearchFamiliaRequest:
    """
    Request to search for court files in Fuero de Familia.

    Unlike Civil/Comercial searches, Familia uses a set-based approach:
    1. Login and set district with FueroType.FAMILIA
    2. Parse the authorized set ID from POSLoguin response
    3. Search by set, then iterate all juzgados to get causas

    Only requires credentials and district_code - no court_id needed upfront.
    """

    credentials: Credentials
    district_code: str  # District tracking code (e.g., "80" for Avellaneda)


# =============================================================================
# RESPONSE MODELS
# =============================================================================


@dataclass
class CourtFile:
    """
    A court file (expediente) returned from search or get operations.

    This represents a case file with its basic metadata.
    """

    id: str  # Internal case ID (nidCausa) - from checkbox value
    court_id: str  # Court identifier (pidJuzgado) - from hidden input
    case_caption: str  # Case title/name - from link text
    status: str  # Current status - Column 1
    reception_number: str  # Nro de Receptoria - Column 2
    file_number: str  # Nro de Expediente - Column 3
    initial_date: Optional[datetime] = None  # Fecha de Inicio - Column 4
    last_update: Optional[datetime] = None  # Date from Ultimo despacho - Column 5
    last_order_title: str = ""  # Title from Ultimo despacho - Column 5
    court_name: str = ""  # Human-readable juzgado name

    # Backwards compatibility alias
    @property
    def received_id(self) -> str:
        """Alias for reception_number (backwards compatibility)."""
        return self.reception_number

    @property
    def procesales_url(self) -> str:
        """URL to view all orders for this file."""
        return f"procesales.asp?nidCausa={self.id}&pidJuzgado={self.court_id}"

    @property
    def last_update_formatted(self) -> str:
        """Last update date formatted as DD/MM/YYYY."""
        if self.last_update is None:
            return "No disponible"
        return self.last_update.strftime("%d/%m/%Y")

    @property
    def initial_date_formatted(self) -> str:
        """Initial date formatted as DD/MM/YYYY."""
        if self.initial_date is None:
            return "No disponible"
        return self.initial_date.strftime("%d/%m/%Y")

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "court_id": self.court_id,
            "court_name": self.court_name,
            "case_caption": self.case_caption,
            "status": self.status,
            "reception_number": self.reception_number,
            "file_number": self.file_number,
            "initial_date": self.initial_date_formatted,
            "last_update": self.last_update_formatted,
            "last_order_title": self.last_order_title,
            "procesales_url": self.procesales_url,
        }


@dataclass
class OrderSummary:
    """
    Summary of a court order (paso procesal) from the file orders page.

    Contains metadata without the full order text.
    """

    date: datetime  # Order date (with time if available)
    title: str  # Order type/title (e.g., "INTIMACION", "SENTENCIA")
    order_code: str  # sCodi - typically the case ID
    position: str  # nPosi - unique order position ID
    file_type: str  # sFile - file type marker (usually "a")
    court_id: str  # pidJuzgado
    fojas: str = ""  # Page numbers (Fojas) - often empty
    is_signed: bool = False  # Whether the order has a digital signature

    @property
    def proveido_url(self) -> str:
        """URL to read the full order text."""
        return (
            f"proveido.asp?pidJuzgado={self.court_id}"
            f"&sCodi={self.order_code}"
            f"&nPosi={self.position}"
            f"&sFile={self.file_type}&MT="
        )

    @property
    def date_formatted(self) -> str:
        """Date formatted as DD/MM/YYYY."""
        return self.date.strftime("%d/%m/%Y")

    @property
    def datetime_formatted(self) -> str:
        """Full datetime formatted as DD/MM/YYYY HH:MM:SS."""
        return self.date.strftime("%d/%m/%Y %H:%M:%S")


@dataclass
class Attachment:
    """An attachment (document) linked to a court order."""

    name: str  # File name (e.g., "descarga.pdf", "testamento+Finderle.pdf")
    url: str  # Full URL to download the attachment

    def to_dict(self) -> dict:
        return {"name": self.name, "url": self.url}


@dataclass
class FileOrder:
    """
    A full court order with its text content.

    Returned from read_order().
    """

    date: datetime  # Order date with time
    title: str  # Order type/title (e.g., "DEMANDA - SE PRESENTA")
    text: str  # Clean order text (without copy/paste markers)
    order_code: str  # sCodi parameter
    position: str  # nPosi parameter
    court_id: str  # pidJuzgado parameter
    case_id: str  # nidCausa (from URL or context)

    # Additional metadata from References section
    signed_by: str = ""  # "Firmado por" - signer name and CUIT
    observation: str = ""  # "Observacion" field
    submission_number: str = ""  # "Nro. Presentacion Electronica"
    submission_date: Optional[datetime] = None  # "Fecha del Escrito"
    attachments: list[Attachment] = field(default_factory=list)

    @property
    def date_formatted(self) -> str:
        """Date formatted as DD/MM/YYYY."""
        return self.date.strftime("%d/%m/%Y")

    @property
    def datetime_formatted(self) -> str:
        """Full datetime formatted as DD/MM/YYYY HH:MM:SS."""
        return self.date.strftime("%d/%m/%Y %H:%M:%S")

    @property
    def attachment_count(self) -> int:
        """Number of attachments."""
        return len(self.attachments)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "date": self.datetime_formatted,
            "title": self.title,
            "text": self.text,
            "order_code": self.order_code,
            "position": self.position,
            "court_id": self.court_id,
            "case_id": self.case_id,
            "signed_by": self.signed_by,
            "observation": self.observation,
            "submission_number": self.submission_number,
            "submission_date": self.submission_date.strftime("%d/%m/%Y %H:%M:%S") if self.submission_date else None,
            "attachments": [a.to_dict() for a in self.attachments],
            "attachment_count": self.attachment_count,
        }


@dataclass
class FullCourtFile:
    """
    Complete court file with all its orders.

    Returned from download_file().
    """

    file: CourtFile  # Basic file info
    orders: list[OrderSummary] = field(default_factory=list)  # All order summaries
    court_name: str = ""  # Full court name from page header
    district_name: str = ""  # District name from page header

    @property
    def order_count(self) -> int:
        """Number of orders in this file."""
        return len(self.orders)

    @property
    def has_orders(self) -> bool:
        """Whether this file has any orders."""
        return len(self.orders) > 0

    @property
    def latest_order(self) -> Optional[OrderSummary]:
        """Most recent order, if any."""
        if not self.orders:
            return None
        return max(self.orders, key=lambda o: o.date)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "file": self.file.to_dict(),
            "orders": [
                {
                    "date": o.datetime_formatted,
                    "title": o.title,
                    "order_code": o.order_code,
                    "position": o.position,
                    "fojas": o.fojas,
                    "is_signed": o.is_signed,
                    "proveido_url": o.proveido_url,
                }
                for o in self.orders
            ],
            "order_count": self.order_count,
            "court_name": self.court_name,
            "district_name": self.district_name,
        }


@dataclass
class OrderWithText:
    """An order with its full text content."""

    date: datetime
    title: str
    text: str
    order_code: str = ""  # sCodi - MEV order code
    position: str = ""  # nPosi - MEV position ID
    signed_by: str = ""
    fojas: str = ""
    error: Optional[str] = None  # If text couldn't be fetched

    @property
    def datetime_formatted(self) -> str:
        """Full datetime formatted as DD/MM/YYYY HH:MM:SS."""
        return self.date.strftime("%d/%m/%Y %H:%M:%S")

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "fecha": self.datetime_formatted,
            "titulo": self.title,
            "texto": self.text,
            "firmado_por": self.signed_by,
            "fojas": self.fojas,
            "error": self.error,
        }


@dataclass
class CausaContext:
    """
    Full causa context with all order texts.

    Used for AI summarization and causa tracking.
    """

    file: CourtFile
    orders: list[OrderWithText] = field(default_factory=list)
    court_name: str = ""
    district_name: str = ""

    @property
    def order_count(self) -> int:
        """Number of orders."""
        return len(self.orders)

    @property
    def successful_orders(self) -> list[OrderWithText]:
        """Orders that were successfully fetched."""
        return [o for o in self.orders if o.error is None]

    @property
    def failed_orders(self) -> list[OrderWithText]:
        """Orders that failed to fetch."""
        return [o for o in self.orders if o.error is not None]

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "causa": {
                "id": self.file.id,
                "court_id": self.file.court_id,
                "caratula": self.file.case_caption,
                "estado": self.file.status,
                "numero_expediente": self.file.file_number,
                "numero_receptoria": self.file.reception_number,
                "fecha_inicio": self.file.initial_date_formatted,
                "juzgado_nombre": self.court_name,
                "departamento_nombre": self.district_name,
            },
            "orders": [o.to_dict() for o in self.orders],
            "order_count": self.order_count,
        }
