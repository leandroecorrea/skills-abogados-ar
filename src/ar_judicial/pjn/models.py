"""Domain models for the PJN service.

This module contains all request and response models used by the PJN service.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# =============================================================================
# CREDENTIAL MODEL
# =============================================================================


@dataclass(frozen=True)
class Credentials:
    """User credentials for PJN authentication (CUIL + password)."""

    username: str  # CUIL number (e.g., "27368195575")
    password: str


# =============================================================================
# TOKEN MODELS
# =============================================================================


@dataclass
class TokenSet:
    """OAuth2/OIDC tokens from PJN SSO."""

    access_token: str
    refresh_token: str
    id_token: str
    token_type: str = "bearer"
    expires_in: int = 300  # seconds
    refresh_expires_in: int = 1800  # seconds
    session_state: str = ""
    scope: str = "openid"
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def is_expired(self) -> bool:
        """Check if access token is expired."""
        elapsed = (datetime.now() - self.created_at).total_seconds()
        return elapsed >= self.expires_in

    @property
    def is_refresh_expired(self) -> bool:
        """Check if refresh token is expired."""
        elapsed = (datetime.now() - self.created_at).total_seconds()
        return elapsed >= self.refresh_expires_in

    @property
    def seconds_until_expiry(self) -> int:
        """Seconds until access token expires."""
        elapsed = (datetime.now() - self.created_at).total_seconds()
        return max(0, int(self.expires_in - elapsed))

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "id_token": self.id_token,
            "token_type": self.token_type,
            "expires_in": self.expires_in,
            "refresh_expires_in": self.refresh_expires_in,
            "session_state": self.session_state,
            "scope": self.scope,
            "is_expired": self.is_expired,
            "seconds_until_expiry": self.seconds_until_expiry,
        }


@dataclass
class UserInfo:
    """User information from ID token claims."""

    sub: str  # Subject (user ID)
    cuil: str
    name: str
    given_name: str
    family_name: str
    email: str
    preferred_username: str

    @classmethod
    def from_token_claims(cls, claims: dict) -> "UserInfo":
        """Create from JWT token claims."""
        return cls(
            sub=claims.get("sub", ""),
            cuil=claims.get("cuil", ""),
            name=claims.get("name", ""),
            given_name=claims.get("given_name", claims.get("givenName", "")),
            family_name=claims.get("family_name", claims.get("familyName", "")),
            email=claims.get("email", ""),
            preferred_username=claims.get("preferred_username", ""),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "sub": self.sub,
            "cuil": self.cuil,
            "name": self.name,
            "given_name": self.given_name,
            "family_name": self.family_name,
            "email": self.email,
            "preferred_username": self.preferred_username,
        }


# =============================================================================
# JURISDICTION MODEL
# =============================================================================


@dataclass
class Jurisdiction:
    """A PJN jurisdiction (federal court)."""

    code: str  # Value in dropdown (e.g., "0", "1", etc.)
    short_code: str  # Abbreviated code (e.g., "CSJ", "CIV", "FLP")
    name: str  # Full name

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "short_code": self.short_code,
            "name": self.name,
        }


# All PJN jurisdictions
PJN_JURISDICTIONS = [
    Jurisdiction("0", "CSJ", "Corte Suprema de Justicia de la Nacion"),
    Jurisdiction("1", "CIV", "Camara Nacional de Apelaciones en lo Civil"),
    Jurisdiction("2", "CAF", "Camara Nacional de Apelaciones en lo Contencioso Administrativo Federal"),
    Jurisdiction("3", "CCF", "Camara Nacional de Apelaciones en lo Civil y Comercial Federal"),
    Jurisdiction("4", "CNE", "Camara Nacional Electoral"),
    Jurisdiction("5", "CSS", "Camara Federal de la Seguridad Social"),
    Jurisdiction("6", "CPE", "Camara Nacional de Apelaciones en lo Penal Economico"),
    Jurisdiction("7", "CNT", "Camara Nacional de Apelaciones del Trabajo"),
    Jurisdiction("8", "CFP", "Camara Criminal y Correccional Federal"),
    Jurisdiction("9", "CCC", "Camara Nacional de Apelaciones en lo Criminal y Correccional"),
    Jurisdiction("10", "COM", "Camara Nacional de Apelaciones en lo Comercial"),
    Jurisdiction("11", "CPF", "Camara Federal de Casacion Penal"),
    Jurisdiction("12", "CPN", "Camara Nacional Casacion Penal"),
    Jurisdiction("13", "FBB", "Justicia Federal de Bahia Blanca"),
    Jurisdiction("14", "FCR", "Justicia Federal de Comodoro Rivadavia"),
    Jurisdiction("15", "FCB", "Justicia Federal de Cordoba"),
    Jurisdiction("16", "FCT", "Justicia Federal de Corrientes"),
    Jurisdiction("17", "FGR", "Justicia Federal de General Roca"),
    Jurisdiction("18", "FLP", "Justicia Federal de La Plata"),
    Jurisdiction("19", "FMP", "Justicia Federal de Mar del Plata"),
    Jurisdiction("20", "FMZ", "Justicia Federal de Mendoza"),
    Jurisdiction("21", "FPO", "Justicia Federal de Posadas"),
    Jurisdiction("22", "FPA", "Justicia Federal de Parana"),
    Jurisdiction("23", "FRE", "Justicia Federal de Resistencia"),
    Jurisdiction("24", "FSA", "Justicia Federal de Salta"),
    Jurisdiction("25", "FRO", "Justicia Federal de Rosario"),
    Jurisdiction("26", "FSM", "Justicia Federal de San Martin"),
    Jurisdiction("27", "FTU", "Justicia Federal de Tucuman"),
]


# =============================================================================
# SEARCH MODELS
# =============================================================================


@dataclass
class SearchRequest:
    """Request to search for cases in PJN."""

    jurisdiction_code: str  # Jurisdiction code (e.g., "18" for La Plata)
    case_number: str  # Case number
    year: str  # Year (4 digits)
    captcha_response: Optional[str] = None  # Captcha solution if required


@dataclass
class CaptchaChallenge:
    """Captcha challenge data extracted from SCW page."""

    site_key: str  # PJN captcha site key
    captcha_url: str  # URL to load captcha
    form_action: str  # Form submission URL
    view_state: str  # JSF ViewState for form submission
    captcha_div_html: str  # Raw HTML of captcha div for rendering

    def to_dict(self) -> dict:
        return {
            "site_key": self.site_key,
            "captcha_url": self.captcha_url,
            "form_action": self.form_action,
            "view_state": self.view_state,
            "captcha_div_html": self.captcha_div_html,
        }


# =============================================================================
# AUTH SESSION MODEL
# =============================================================================


@dataclass
class AuthSession:
    """Authenticated session with PJN."""

    tokens: TokenSet
    user_info: UserInfo
    cookies: dict[str, str] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        """Check if session is still valid (has non-expired tokens)."""
        return not self.tokens.is_expired or not self.tokens.is_refresh_expired

    def to_dict(self) -> dict:
        return {
            "tokens": self.tokens.to_dict(),
            "user_info": self.user_info.to_dict(),
            "is_valid": self.is_valid,
        }


# =============================================================================
# EXPEDIENTE (CASE) MODELS
# =============================================================================


@dataclass
class Expediente:
    """A case/expediente from PJN SCW."""

    numero: str  # Case number (e.g., "CIV 008078/2025")
    dependencia: str  # Court/office (e.g., "JUZGADO CIVIL 88")
    caratula: str  # Case caption/title
    situacion: str  # Status (e.g., "EN LETRA", "EN DESPACHO")
    ultima_actualizacion: str  # Last update date
    row_index: int  # Row index in the table (for navigation)
    internal_id: Optional[str] = None  # Internal PJN ID

    def to_dict(self) -> dict:
        return {
            "numero": self.numero,
            "dependencia": self.dependencia,
            "caratula": self.caratula,
            "situacion": self.situacion,
            "ultima_actualizacion": self.ultima_actualizacion,
            "row_index": self.row_index,
            "internal_id": self.internal_id,
        }


@dataclass
class ExpedienteList:
    """List of expedientes with pagination info."""

    expedientes: list[Expediente]
    total_count: int
    current_page: int = 1
    total_pages: int = 1
    view_state: str = ""  # JSF ViewState for pagination/navigation

    def to_dict(self) -> dict:
        return {
            "expedientes": [e.to_dict() for e in self.expedientes],
            "total_count": self.total_count,
            "current_page": self.current_page,
            "total_pages": self.total_pages,
        }


@dataclass
class ExpedienteDetail:
    """Detailed expediente data from the detail page (Datos Generales section)."""

    numero: str  # Case number (e.g., "CIV 008078/2025")
    jurisdiccion: str  # Jurisdiction (e.g., "Cámara Nacional de Apelaciones en lo Civil")
    dependencia: str  # Court/office (e.g., "JUZGADO CIVIL 88")
    situacion: str  # Current status (e.g., "EN LETRA")
    caratula: str  # Case caption/title

    def to_dict(self) -> dict:
        return {
            "numero": self.numero,
            "jurisdiccion": self.jurisdiccion,
            "dependencia": self.dependencia,
            "situacion": self.situacion,
            "caratula": self.caratula,
        }


# =============================================================================
# ACTUACIONES (COURT ACTIONS) MODELS
# =============================================================================


@dataclass
class Actuacion:
    """A single court action/proceeding from the expediente detail page."""

    oficina: str  # Office code (e.g., "051", "I88")
    fecha: str  # Date (e.g., "3/02/2026")
    tipo: str  # Action type (e.g., "MOVIMIENTO", "FIRMA DESPACHO", "ESCRITO AGREGADO")
    descripcion: str  # Description/detail
    fojas: Optional[str] = None  # Page numbers (e.g., "209 / 209")
    documento_url: Optional[str] = None  # View URL
    documento_download_url: Optional[str] = None  # Download URL
    documento_tipo: Optional[str] = None  # Document type ("despacho", "cedula")

    def to_dict(self) -> dict:
        return {
            "oficina": self.oficina,
            "fecha": self.fecha,
            "tipo": self.tipo,
            "descripcion": self.descripcion,
            "fojas": self.fojas,
            "documento_url": self.documento_url,
            "documento_download_url": self.documento_download_url,
            "documento_tipo": self.documento_tipo,
        }


@dataclass
class ActuacionesList:
    """List of actuaciones with pagination info."""

    actuaciones: list[Actuacion]
    current_page: int = 1
    total_pages: int = 1

    def to_dict(self) -> dict:
        return {
            "actuaciones": [a.to_dict() for a in self.actuaciones],
            "current_page": self.current_page,
            "total_pages": self.total_pages,
        }


# =============================================================================
# INTERVINIENTES (PARTIES) MODELS
# =============================================================================


@dataclass
class Letrado:
    """A lawyer/legal representative associated with a party."""

    tipo: str  # "LETRADO PATROCINANTE", "LETRADO DEFENSOR OFICIAL"
    nombre: str
    tomo_folio: Optional[str] = None  # "Tomo: 140 Folio: 473 - CPACF"
    iej: Optional[str] = None  # CUIL identifier

    def to_dict(self) -> dict:
        return {
            "tipo": self.tipo,
            "nombre": self.nombre,
            "tomo_folio": self.tomo_folio,
            "iej": self.iej,
        }


@dataclass
class Interviniente:
    """A party in the case (actor, demandado, tercero, etc.)."""

    tipo: str  # "ACTOR", "DEMANDADO", "TERCERO", "MEDIADOR"
    nombre: str
    tomo_folio: Optional[str] = None
    iej: Optional[str] = None
    letrados: list[Letrado] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tipo": self.tipo,
            "nombre": self.nombre,
            "tomo_folio": self.tomo_folio,
            "iej": self.iej,
            "letrados": [l.to_dict() for l in self.letrados],
        }


@dataclass
class Fiscal:
    """A prosecutor/fiscal assigned to the case."""

    fiscalia: str
    fiscal: str
    iej: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "fiscalia": self.fiscalia,
            "fiscal": self.fiscal,
            "iej": self.iej,
        }


@dataclass
class IntervinientesList:
    """All parties involved in a case."""

    partes: list[Interviniente]
    fiscales: list[Fiscal] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "partes": [p.to_dict() for p in self.partes],
            "fiscales": [f.to_dict() for f in self.fiscales],
        }


# =============================================================================
# RELACIONADOS (EXPEDIENTES BY ROLE) MODELS
# =============================================================================


# =============================================================================
# SCW SEARCH RESULT MODEL
# =============================================================================


@dataclass
class SCWResult:
    """A single result from SCW public search."""

    numero: str
    dependencia: str
    caratula: str
    situacion: str
    ultima_actualizacion: str
    tomo: str = ""
    letra: str = ""

    def to_dict(self) -> dict:
        return {
            "numero": self.numero,
            "dependencia": self.dependencia,
            "caratula": self.caratula,
            "situacion": self.situacion,
            "ultima_actualizacion": self.ultima_actualizacion,
            "tomo": self.tomo,
            "letra": self.letra,
        }


@dataclass
class RelacionadosProfile:
    """A role profile on the consultaListaRelacionados page."""

    nombre: str  # Profile name (e.g., "AUTORIZADO NE", "LETRADO")
    index: int  # Index for form submission (0, 1, etc.)

    def to_dict(self) -> dict:
        return {
            "nombre": self.nombre,
            "index": self.index,
        }


@dataclass
class RelacionadosPage:
    """Page data from consultaListaRelacionados.seam."""

    profiles: list[RelacionadosProfile]  # Available profiles (before selection)
    expedientes: ExpedienteList  # Expedientes (after profile selection)
    view_state: str = ""  # JSF ViewState for form submission
    selected_profile: Optional[str] = None  # Currently selected profile name
    is_empty: bool = False  # True if "No se han encontrado expedientes"

    def to_dict(self) -> dict:
        return {
            "profiles": [p.to_dict() for p in self.profiles],
            "expedientes": self.expedientes.to_dict() if self.expedientes else None,
            "view_state": self.view_state,
            "selected_profile": self.selected_profile,
            "is_empty": self.is_empty,
        }
