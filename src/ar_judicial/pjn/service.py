"""PJN Service - Main service for PJN (Poder Judicial de la Nacion) operations.

This module provides a high-level async service for interacting with
the PJN portal and SCW (Sistema de Consulta Web).
"""

import asyncio
import logging
from typing import Optional

from .http_client import PJNHttpClient, HttpClientConfig
from .models import (
    AuthSession,
    CaptchaChallenge,
    Credentials,
    Expediente,
    ExpedienteList,
    RelacionadosPage,
    TokenSet,
    UserInfo,
    PJN_JURISDICTIONS,
)
from .parsers import CaptchaParser, FavoritosParser, RelacionadosParser, SearchFormParser
from .exceptions import AuthenticationError, CaptchaRequiredError

logger = logging.getLogger(__name__)




class PJNService:
    """
    Service for PJN operations.

    Provides:
    - Authentication with PJN SSO (Keycloak)
    - Access to SCW (Sistema de Consulta Web)
    - Case search functionality (with captcha handling)

    Usage:
        async with PJNService() as service:
            session = await service.authenticate()
            captcha = await service.get_search_captcha()
    """

    def __init__(
        self,
        config: Optional[HttpClientConfig] = None,
        credentials: Optional[Credentials] = None,
    ):
        """
        Initialize the PJN service.

        Args:
            config: HTTP client configuration
            credentials: User credentials (required for authentication)
        """
        self._config = config or HttpClientConfig()
        self._credentials = credentials
        self._client: Optional[PJNHttpClient] = None
        self._session: Optional[AuthSession] = None

        # Parsers
        self._captcha_parser = CaptchaParser()
        self._form_parser = SearchFormParser()
        self._favoritos_parser = FavoritosParser()
        self._relacionados_parser = RelacionadosParser()

    async def __aenter__(self) -> "PJNService":
        """Async context manager entry."""
        self._client = PJNHttpClient(self._config)
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def close(self) -> None:
        """Close the service and release resources."""
        if self._client is not None:
            await self._client.close()
            self._client = None
            self._session = None

    # =========================================================================
    # AUTHENTICATION
    # =========================================================================

    async def authenticate(
        self,
        credentials: Optional[Credentials] = None,
    ) -> AuthSession:
        """
        Authenticate with PJN.

        Args:
            credentials: Override credentials (uses default if not provided)

        Returns:
            AuthSession with tokens and user info

        Raises:
            AuthenticationError: If authentication fails
        """
        if self._client is None:
            self._client = PJNHttpClient(self._config)
            await self._client.__aenter__()

        creds = credentials or self._credentials
        if creds is None:
            raise AuthenticationError("No credentials provided for PJN authentication")
        tokens = await self._client.authenticate(creds)
        user_info = self._client.get_user_info_from_token()

        if user_info is None:
            user_info = UserInfo(
                sub="",
                cuil=creds.username,
                name="",
                given_name="",
                family_name="",
                email="",
                preferred_username=creds.username,
            )

        self._session = AuthSession(
            tokens=tokens,
            user_info=user_info,
            cookies=self._client.get_cookies(),
        )

        logger.info(f"Authenticated as: {user_info.name} ({user_info.cuil})")
        return self._session

    async def refresh_session(self) -> AuthSession:
        """Refresh the current session tokens."""
        if self._client is None or self._session is None:
            raise AuthenticationError("Not authenticated")

        tokens = await self._client.refresh_tokens()
        self._session.tokens = tokens
        self._session.cookies = self._client.get_cookies()

        return self._session

    @property
    def session(self) -> Optional[AuthSession]:
        """Get current session."""
        return self._session

    @property
    def is_authenticated(self) -> bool:
        """Check if service is authenticated."""
        return self._session is not None and self._session.is_valid

    # =========================================================================
    # SCW (Sistema de Consulta Web)
    # =========================================================================

    async def get_search_page(self) -> str:
        """
        Get the SCW search page HTML.

        Returns:
            Raw HTML of the search page
        """
        await self._ensure_authenticated()
        assert self._client is not None

        response = await self._client.get_scw("/consulta/busqueda.seam")
        return response.text

    async def get_search_captcha(self) -> CaptchaChallenge:
        """
        Get captcha challenge from SCW search page.

        Returns:
            CaptchaChallenge with captcha configuration

        Raises:
            CaptchaRequiredError: If captcha is found (with captcha data)
            AuthenticationError: If not authenticated
        """
        html_content = await self.get_search_page()
        captcha = self._captcha_parser.parse(html_content)

        if captcha is None:
            # No captcha found - might mean we're already authenticated
            # or the page structure changed
            raise CaptchaRequiredError(
                "Could not extract captcha from search page",
                captcha_html="",
            )

        return captcha

    async def get_home_page(self) -> str:
        """
        Get the SCW home page HTML.

        Returns:
            Raw HTML of the home page
        """
        await self._ensure_authenticated()
        assert self._client is not None

        response = await self._client.get_scw("/home.seam")
        return response.text

    # =========================================================================
    # EXPEDIENTES (MIS EXPEDIENTES / FAVORITOS)
    # =========================================================================

    async def get_expedientes(self) -> ExpedienteList:
        """
        Get the list of user's expedientes (Mis Expedientes / Favoritos).

        Returns:
            ExpedienteList with parsed expedientes and pagination info
        """
        await self._ensure_authenticated()
        assert self._client is not None

        response = await self._client.get_favoritos_page()
        return self._favoritos_parser.parse(response.text)

    async def get_expedientes_raw(self) -> str:
        """
        Get raw HTML of the favoritos (Mis Expedientes) page.

        Returns:
            Raw HTML content
        """
        await self._ensure_authenticated()
        assert self._client is not None

        response = await self._client.get_favoritos_page()
        return response.text

    async def get_expediente_detail(self, row_index: int) -> str:
        """
        Get expediente detail page for a specific expediente.

        This navigates to the detail view by submitting the JSF form.

        Args:
            row_index: Index of the expediente in the list (0-based)

        Returns:
            Raw HTML of the expediente detail page
        """
        await self._ensure_authenticated()
        assert self._client is not None

        # First get the favoritos page to get ViewState and form IDs
        response = await self._client.get_favoritos_page()
        exp_list = self._favoritos_parser.parse(response.text)
        form_ids = self._favoritos_parser.extract_form_ids(response.text)

        if not exp_list.view_state:
            raise ValueError("Could not extract ViewState from favoritos page")

        if not form_ids.get("form_id"):
            raise ValueError("Could not extract form IDs from favoritos page")

        # Navigate to detail using extracted form IDs
        detail_response = await self._client.view_expediente_detail(
            row_index=row_index,
            view_state=exp_list.view_state,
            form_id=form_ids["form_id"],
            table_part=form_ids.get("table_part", "j_idt172"),
            button_suffix=form_ids.get("button_suffix", "j_idt223"),
        )

        return detail_response.text

    # =========================================================================
    # RELACIONADOS (EXPEDIENTES BY ROLE)
    # =========================================================================

    async def get_relacionados(self) -> RelacionadosPage:
        """
        Get the relacionados page (expedientes where user is related by role).

        Initially returns available profiles (AUTORIZADO NE, LETRADO).
        After selecting a profile, returns expedientes for that role.

        Returns:
            RelacionadosPage with profiles or expedientes
        """
        await self._ensure_authenticated()
        assert self._client is not None

        response = await self._client.get_relacionados_page()
        return self._relacionados_parser.parse(response.text)

    async def get_relacionados_by_profile(self, profile_index: int = 0) -> RelacionadosPage:
        """
        Get expedientes for a specific profile/role.

        Args:
            profile_index: Index of the profile (0=AUTORIZADO NE, 1=LETRADO typically)

        Returns:
            RelacionadosPage with expedientes for the selected profile
        """
        await self._ensure_authenticated()
        assert self._client is not None

        # First get the page to extract ViewState and form IDs
        initial_response = await self._client.get_relacionados_page()
        initial_page = self._relacionados_parser.parse(initial_response.text)
        form_ids = self._relacionados_parser.extract_form_ids(initial_response.text)

        if not initial_page.view_state:
            raise ValueError("Could not extract ViewState from relacionados page")

        # Select the profile
        response = await self._client.select_relacionados_profile(
            view_state=initial_page.view_state,
            profile_index=profile_index,
            form_id=form_ids.get("form_id", "j_idt76:j_idt78"),
        )

        return self._relacionados_parser.parse(response.text)

    async def get_relacionados_by_profile_page(
        self,
        profile_index: int,
        page: int,
    ) -> RelacionadosPage:
        """
        Get a specific page of expedientes for a profile.

        For page 1, selects the profile and returns results.
        For page > 1, selects the profile, then fetches the page via AJAX.

        Args:
            profile_index: Index of the profile
            page: Page number (1-based)

        Returns:
            RelacionadosPage with expedientes for the requested page
        """
        await self._ensure_authenticated()
        assert self._client is not None

        # Get initial page, extract ViewState, select profile
        initial_response = await self._client.get_relacionados_page()
        initial_page = self._relacionados_parser.parse(initial_response.text)
        form_ids = self._relacionados_parser.extract_form_ids(initial_response.text)

        if not initial_page.view_state:
            raise ValueError("Could not extract ViewState from relacionados page")

        # Select the profile (gets page 1)
        response = await self._client.select_relacionados_profile(
            view_state=initial_page.view_state,
            profile_index=profile_index,
            form_id=form_ids.get("form_id", "j_idt76:j_idt78"),
        )

        first_page_html = response.text
        first_page_result = self._relacionados_parser.parse(first_page_html)

        if page <= 1:
            return first_page_result

        # Extract pagination element IDs and form ID from page 1
        page_ids = self._relacionados_parser.extract_page_ids(first_page_html)
        table_form_id = self._relacionados_parser.extract_form_id_from_table(first_page_html)

        if page not in page_ids:
            return first_page_result

        if not first_page_result.view_state:
            raise ValueError("Could not extract ViewState for pagination")

        # Fetch the requested page via AJAX
        ajax_response = await self._client.fetch_relacionados_page(
            view_state=first_page_result.view_state,
            page_element_id=page_ids[page],
            form_id=table_form_id,
        )

        expedientes = self._relacionados_parser.parse_from_ajax(ajax_response.text)
        return RelacionadosPage(
            profiles=first_page_result.profiles,
            expedientes=expedientes,
            view_state=first_page_result.view_state,
            selected_profile=first_page_result.selected_profile,
            is_empty=len(expedientes.expedientes) == 0,
        )

    async def get_relacionados_expediente_detail(
        self,
        profile_index: int,
        row_index: int,
    ) -> tuple[str, str]:
        """
        Get expediente detail page navigating from the relacionados list.

        Steps:
        1. Go to relacionados page
        2. Select the profile
        3. Extract form IDs from the expedientes table
        4. Click on the row to navigate to the detail page

        Args:
            profile_index: Index of the profile (0=AUTORIZADO NE, 1=LETRADO typically)
            row_index: Index of the expediente in the list (0-based)

        Returns:
            Tuple of (detail_html, detail_url)
        """
        await self._ensure_authenticated()
        assert self._client is not None

        # Select the profile to get the expedientes page
        initial_response = await self._client.get_relacionados_page()
        initial_page = self._relacionados_parser.parse(initial_response.text)
        profile_form_ids = self._relacionados_parser.extract_form_ids(initial_response.text)

        if not initial_page.view_state:
            raise ValueError("Could not extract ViewState from relacionados page")

        response = await self._client.select_relacionados_profile(
            view_state=initial_page.view_state,
            profile_index=profile_index,
            form_id=profile_form_ids.get("form_id", "j_idt76:j_idt78"),
        )

        exp_html = response.text
        exp_page = self._relacionados_parser.parse(exp_html)

        if not exp_page.view_state:
            raise ValueError("Could not extract ViewState from expedientes page")

        # Extract form IDs for the expedientes table (same parser as favoritos)
        table_form_ids = self._favoritos_parser.extract_form_ids(exp_html)

        if not table_form_ids.get("form_id"):
            raise ValueError("Could not extract form IDs from expedientes table")

        # Navigate to detail
        detail_response = await self._client.view_expediente_detail(
            row_index=row_index,
            view_state=exp_page.view_state,
            form_id=table_form_ids["form_id"],
            table_part=table_form_ids.get("table_part", "j_idt179"),
            button_suffix=table_form_ids.get("button_suffix", "j_idt230"),
            source_page="consultaListaRelacionados",
        )

        return detail_response.text, str(detail_response.url)

    async def get_all_relacionados(self) -> dict:
        """
        Fetch ALL expedientes across ALL profiles (paginating through every page).

        Uses the "Siguiente" (Next) button to navigate through pages, which is
        more reliable than numbered page IDs because:
        - It doesn't depend on finding a specific pagination div ID
        - It naturally handles PJN's sliding-window page numbers
        - It's the same proven approach used for actuaciones pagination

        Returns a dict with:
        - profiles: list of RelacionadosProfile
        - expedientes_by_profile: dict mapping profile index -> list of Expediente
        """
        await self._ensure_authenticated()
        assert self._client is not None

        MAX_PAGES_PER_PROFILE = 200

        # Get initial page to discover profiles
        initial_response = await self._client.get_relacionados_page()
        initial_page = self._relacionados_parser.parse(initial_response.text)
        profile_form_ids = self._relacionados_parser.extract_form_ids(initial_response.text)

        if not initial_page.view_state:
            raise ValueError("Could not extract ViewState from relacionados page")

        profiles = initial_page.profiles
        expedientes_by_profile: dict[int, list] = {}

        for profile in profiles:
            try:
                # Select the profile (gets page 1)
                response = await self._client.select_relacionados_profile(
                    view_state=initial_page.view_state,
                    profile_index=profile.index,
                    form_id=profile_form_ids.get("form_id", "j_idt76:j_idt78"),
                )

                page_html = response.text
                page_result = self._relacionados_parser.parse(page_html)
                all_expedientes = list(
                    page_result.expedientes.expedientes
                ) if page_result.expedientes else []

                logger.info(
                    f"Profile {profile.nombre} page 1: "
                    f"{len(all_expedientes)} expedientes"
                )

                # Paginate using "Siguiente" button
                table_form_id = self._relacionados_parser.extract_form_id_from_table(page_html)
                current_view_state = page_result.view_state
                current_html = page_html
                pages_fetched = 1

                for _ in range(MAX_PAGES_PER_PROFILE):
                    siguiente_id = self._relacionados_parser.extract_next_page_id(current_html)
                    if not siguiente_id:
                        break  # No more pages

                    await asyncio.sleep(0.3)  # Rate limit

                    ajax_response = await self._client.fetch_relacionados_page(
                        view_state=current_view_state,
                        page_element_id=siguiente_id,
                        form_id=table_form_id,
                    )

                    if ajax_response.status_code != 200:
                        logger.warning(
                            f"AJAX pagination failed for profile {profile.nombre} "
                            f"page {pages_fetched + 1}: HTTP {ajax_response.status_code}"
                        )
                        break

                    ajax_text = ajax_response.text
                    pages_fetched += 1

                    # Parse expedientes from AJAX response
                    page_expedientes = self._relacionados_parser.parse_from_ajax(ajax_text)
                    if not page_expedientes.expedientes:
                        logger.warning(
                            f"Profile {profile.nombre} page {pages_fetched}: "
                            f"0 expedientes parsed from AJAX (stopping)"
                        )
                        break

                    all_expedientes.extend(page_expedientes.expedientes)
                    logger.info(
                        f"Profile {profile.nombre} page {pages_fetched}: "
                        f"{len(page_expedientes.expedientes)} expedientes"
                    )

                    # Update ViewState for next request
                    new_vs = self._relacionados_parser.extract_view_state_from_ajax(ajax_text)
                    if new_vs:
                        current_view_state = new_vs

                    # Extract HTML for next iteration's Siguiente check
                    ajax_html = self._relacionados_parser.extract_html_from_ajax(ajax_text)
                    if ajax_html:
                        current_html = ajax_html
                    else:
                        break

                expedientes_by_profile[profile.index] = all_expedientes
                logger.info(
                    f"Profile {profile.nombre}: {len(all_expedientes)} total expedientes "
                    f"across {pages_fetched} page(s)"
                )

            except Exception as e:
                logger.warning(f"Failed to fetch all pages for profile {profile.nombre}: {e}")
                expedientes_by_profile[profile.index] = []

            # Re-fetch initial page for next profile (fresh ViewState)
            if profile != profiles[-1]:
                initial_response = await self._client.get_relacionados_page()
                initial_page = self._relacionados_parser.parse(initial_response.text)
                profile_form_ids = self._relacionados_parser.extract_form_ids(
                    initial_response.text
                )

        return {
            "profiles": profiles,
            "expedientes_by_profile": expedientes_by_profile,
        }

    async def find_expediente_detail(
        self,
        numero: str,
        dependencia: Optional[str] = None,
    ) -> tuple[str, str]:
        """
        Find an expediente by numero (+ dependencia, if given) across ALL profiles and pages,
        then navigate to its detail page.

        This is more reliable than direct navigation with row_index because:
        - row_index is page-relative (0-14 per page), so page-2 items would
          navigate to the wrong row on page 1
        - This method searches page-by-page and clicks the correct row from
          the correct page with the correct ViewState

        Returns:
            Tuple of (detail_html, detail_url)

        Raises:
            Exception if expediente not found across all profiles/pages
        """
        import unicodedata

        def _norm(s: str) -> str:
            return unicodedata.normalize("NFC", " ".join(s.strip().split()))

        await self._ensure_authenticated()
        assert self._client is not None

        MAX_PAGES_PER_PROFILE = 200

        initial_response = await self._client.get_relacionados_page()
        initial_page = self._relacionados_parser.parse(initial_response.text)
        profile_form_ids = self._relacionados_parser.extract_form_ids(initial_response.text)

        if not initial_page.view_state:
            raise ValueError("Could not extract ViewState from relacionados page")

        all_found_numeros = []

        for profile in initial_page.profiles:
            response = await self._client.select_relacionados_profile(
                view_state=initial_page.view_state,
                profile_index=profile.index,
                form_id=profile_form_ids.get("form_id", "j_idt76:j_idt78"),
            )

            page_html = response.text
            page_result = self._relacionados_parser.parse(page_html)
            current_view_state = page_result.view_state

            # Search page 1
            if page_result.expedientes:
                for exp in page_result.expedientes.expedientes:
                    all_found_numeros.append(exp.numero)
                    if _norm(exp.numero) == _norm(numero) and (not dependencia or _norm(exp.dependencia) == _norm(dependencia)):
                        logger.info(
                            f"Found expediente {numero} on profile {profile.nombre} page 1 row {exp.row_index}"
                        )
                        form_ids = self._favoritos_parser.extract_form_ids(page_html)
                        detail_response = await self._client.view_expediente_detail(
                            row_index=exp.row_index,
                            view_state=current_view_state,
                            form_id=form_ids["form_id"],
                            table_part=form_ids.get("table_part", "j_idt179"),
                            button_suffix=form_ids.get("button_suffix", "j_idt230"),
                            source_page="consultaListaRelacionados",
                        )
                        return detail_response.text, str(detail_response.url)

            # Search subsequent pages via Siguiente
            table_form_id = self._relacionados_parser.extract_form_id_from_table(page_html)
            current_html = page_html

            for _ in range(MAX_PAGES_PER_PROFILE):
                siguiente_id = self._relacionados_parser.extract_next_page_id(current_html)
                if not siguiente_id:
                    break

                await asyncio.sleep(0.3)

                ajax_response = await self._client.fetch_relacionados_page(
                    view_state=current_view_state,
                    page_element_id=siguiente_id,
                    form_id=table_form_id,
                )

                if ajax_response.status_code != 200:
                    break

                ajax_text = ajax_response.text

                # Update ViewState
                new_vs = self._relacionados_parser.extract_view_state_from_ajax(ajax_text)
                if new_vs:
                    current_view_state = new_vs

                # Extract HTML for parsing + next Siguiente check
                ajax_html = self._relacionados_parser.extract_html_from_ajax(ajax_text)
                if not ajax_html:
                    break

                current_html = ajax_html
                page_exps = self._relacionados_parser.parse_from_ajax(ajax_text)

                for exp in page_exps.expedientes:
                    all_found_numeros.append(exp.numero)
                    if _norm(exp.numero) == _norm(numero) and (not dependencia or _norm(exp.dependencia) == _norm(dependencia)):
                        logger.info(
                            f"Found expediente {numero} on profile {profile.nombre} "
                            f"(paginated) row {exp.row_index}"
                        )
                        # Navigate to detail from the CURRENT page (correct ViewState)
                        form_ids = self._favoritos_parser.extract_form_ids(ajax_html)
                        detail_response = await self._client.view_expediente_detail(
                            row_index=exp.row_index,
                            view_state=current_view_state,
                            form_id=form_ids["form_id"],
                            table_part=form_ids.get("table_part", "j_idt179"),
                            button_suffix=form_ids.get("button_suffix", "j_idt230"),
                            source_page="consultaListaRelacionados",
                        )
                        return detail_response.text, str(detail_response.url)

                if not page_exps.expedientes:
                    break

            # Re-fetch initial page for next profile
            if profile != initial_page.profiles[-1]:
                initial_response = await self._client.get_relacionados_page()
                initial_page = self._relacionados_parser.parse(initial_response.text)
                profile_form_ids = self._relacionados_parser.extract_form_ids(
                    initial_response.text
                )

        logger.warning(
            f"Expediente not found: numero={numero!r}, dependencia={dependencia!r}. "
            f"Searched {len(all_found_numeros)} expedientes: {all_found_numeros}"
        )
        raise Exception(
            f"No se encontró el expediente {numero} en PJN. "
            "Verifique que el expediente esté en sus Relacionados."
        )

    async def get_relacionados_raw(self) -> str:
        """
        Get raw HTML of the relacionados page.

        Returns:
            Raw HTML content
        """
        await self._ensure_authenticated()
        assert self._client is not None

        response = await self._client.get_relacionados_page()
        return response.text

    # =========================================================================
    # API ENDPOINTS
    # =========================================================================

    async def get_eventos(self) -> dict:
        """
        Get user events/notifications.

        Returns:
            JSON response from eventos API
        """
        await self._ensure_authenticated()
        assert self._client is not None

        response = await self._client.get_api("/eventos")
        if response.status_code == 200:
            return response.json()
        return {"items": [], "error": f"HTTP {response.status_code}"}

    # =========================================================================
    # JURISDICTIONS
    # =========================================================================

    def get_jurisdictions(self) -> list[dict]:
        """Get all available PJN jurisdictions."""
        return [j.to_dict() for j in PJN_JURISDICTIONS]

    # =========================================================================
    # INTERNAL
    # =========================================================================

    async def _ensure_authenticated(self) -> None:
        """Ensure service is authenticated."""
        if self._session is None:
            await self.authenticate()
        elif not self._session.is_valid:
            if self._session.tokens.is_refresh_expired:
                # Full re-auth needed
                await self.authenticate()
            else:
                # Just refresh tokens
                await self.refresh_session()
