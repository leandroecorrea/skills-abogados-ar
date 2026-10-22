"""HTTP client for PJN service.

Handles authentication flow with Keycloak SSO and API requests.
"""

import html
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import httpx

from .exceptions import AuthenticationError, NetworkError, TokenError
from .models import Credentials, TokenSet, UserInfo


@dataclass
class HttpClientConfig:
    """Configuration for the HTTP client."""

    portal_url: str = "https://portalpjn.pjn.gov.ar"
    sso_url: str = "https://sso.pjn.gov.ar"
    scw_url: str = "https://scw.pjn.gov.ar"
    api_url: str = "https://api.pjn.gov.ar"
    timeout: float = 30.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/144.0.0.0 Safari/537.36"
    )


class PJNHttpClient:
    """
    HTTP client for PJN operations.

    Handles:
    - Keycloak SSO authentication (OIDC flow)
    - Token management (access, refresh, id tokens)
    - API requests with Bearer authentication
    - Cookie management for SCW requests
    """

    DEFAULT_HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="144"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }

    def __init__(self, config: Optional[HttpClientConfig] = None):
        self.config = config or HttpClientConfig()
        self._client: Optional[httpx.AsyncClient] = None
        self._tokens: Optional[TokenSet] = None

    async def __aenter__(self) -> "PJNHttpClient":
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _ensure_client(self) -> None:
        if self._client is None:
            headers = {
                **self.DEFAULT_HEADERS,
                "User-Agent": self.config.user_agent,
            }
            self._client = httpx.AsyncClient(
                follow_redirects=False,  # We handle redirects manually
                timeout=self.config.timeout,
                headers=headers,
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self._tokens = None

    # =========================================================================
    # AUTHENTICATION
    # =========================================================================

    async def authenticate(self, credentials: Credentials) -> TokenSet:
        """
        Authenticate with PJN using OIDC flow.

        Steps:
        1. GET portal to init session
        2. GET SSO 3p-cookies check
        3. GET SSO OIDC auth endpoint -> login page
        4. POST credentials -> redirect with auth code
        5. Exchange auth code for tokens

        Returns:
            TokenSet with access, refresh, and id tokens
        """
        await self._ensure_client()
        assert self._client is not None

        # Step 1: GET portal homepage
        await self._client.get(
            f"{self.config.portal_url}/",
            headers=self.DEFAULT_HEADERS,
        )

        # Step 2: 3p-cookies setup
        self._client.cookies.set(
            "KEYCLOAK_3P_COOKIE_SAMESITE", "supported", domain="sso.pjn.gov.ar"
        )
        self._client.cookies.set(
            "KEYCLOAK_3P_COOKIE", "supported", domain="sso.pjn.gov.ar"
        )

        # Step 3: OIDC auth request
        state = str(uuid.uuid4())
        nonce = str(uuid.uuid4())

        auth_params = {
            "client_id": "pjn-portal",
            "redirect_uri": f"{self.config.portal_url}/",
            "state": state,
            "response_mode": "fragment",
            "response_type": "code",
            "scope": "openid",
            "nonce": nonce,
        }

        headers = {**self.DEFAULT_HEADERS}
        headers["Referer"] = f"{self.config.portal_url}/"
        headers["Sec-Fetch-Site"] = "same-site"

        response = await self._client.get(
            f"{self.config.sso_url}/auth/realms/pjn/protocol/openid-connect/auth",
            params=auth_params,
            headers=headers,
        )

        # Follow redirect to login page if needed
        if response.status_code in (301, 302, 303, 307):
            redirect_url = response.headers.get("location")
            if redirect_url:
                response = await self._client.get(redirect_url, headers=headers)

        # Step 4: Extract form action and submit credentials
        form_action = self._extract_form_action(response.text)
        if not form_action:
            raise AuthenticationError(
                "Could not find login form",
                {"status": response.status_code},
            )

        login_data = {
            "username": credentials.username,
            "password": credentials.password,
            "credentialId": "",
        }

        headers = {**self.DEFAULT_HEADERS}
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["Origin"] = "null"
        headers["Cache-Control"] = "max-age=0"
        headers["Sec-Fetch-Site"] = "same-origin"

        response = await self._client.post(
            form_action,
            data=login_data,
            headers=headers,
        )

        # Check for auth code in redirect
        auth_code = None
        if response.status_code in (301, 302, 303, 307):
            redirect_url = response.headers.get("location", "")
            if "code=" in redirect_url:
                code_match = re.search(r"code=([^&\s]+)", redirect_url)
                if code_match:
                    auth_code = code_match.group(1)
            elif "error" in redirect_url:
                raise AuthenticationError(
                    "Authentication failed - invalid credentials",
                    {"redirect": redirect_url},
                )

        if not auth_code:
            # Check if response contains error message
            if "error" in response.text.lower() or "invalid" in response.text.lower():
                raise AuthenticationError(
                    "Authentication failed - invalid credentials or session expired"
                )
            raise AuthenticationError(
                "Authentication failed - no authorization code received"
            )

        # Step 5: Exchange code for tokens
        self._tokens = await self._exchange_code_for_tokens(auth_code)
        return self._tokens

    async def _exchange_code_for_tokens(self, auth_code: str) -> TokenSet:
        """Exchange authorization code for tokens."""
        assert self._client is not None

        token_data = {
            "grant_type": "authorization_code",
            "client_id": "pjn-portal",
            "code": auth_code,
            "redirect_uri": f"{self.config.portal_url}/",
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": self.config.user_agent,
        }

        response = await self._client.post(
            f"{self.config.sso_url}/auth/realms/pjn/protocol/openid-connect/token",
            data=token_data,
            headers=headers,
        )

        if response.status_code != 200:
            raise TokenError(
                f"Token exchange failed: {response.status_code}",
                {"response": response.text[:200]},
            )

        data = response.json()
        return TokenSet(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            id_token=data["id_token"],
            token_type=data.get("token_type", "bearer"),
            expires_in=data.get("expires_in", 300),
            refresh_expires_in=data.get("refresh_expires_in", 1800),
            session_state=data.get("session_state", ""),
            scope=data.get("scope", "openid"),
            created_at=datetime.now(),
        )

    async def refresh_tokens(self) -> TokenSet:
        """Refresh access token using refresh token."""
        if self._tokens is None:
            raise TokenError("No tokens to refresh")

        if self._tokens.is_refresh_expired:
            raise TokenError("Refresh token is expired - re-authentication required")

        await self._ensure_client()
        assert self._client is not None

        token_data = {
            "grant_type": "refresh_token",
            "client_id": "pjn-portal",
            "refresh_token": self._tokens.refresh_token,
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": self.config.user_agent,
        }

        response = await self._client.post(
            f"{self.config.sso_url}/auth/realms/pjn/protocol/openid-connect/token",
            data=token_data,
            headers=headers,
        )

        if response.status_code != 200:
            raise TokenError(
                f"Token refresh failed: {response.status_code}",
                {"response": response.text[:200]},
            )

        data = response.json()
        self._tokens = TokenSet(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            id_token=data["id_token"],
            token_type=data.get("token_type", "bearer"),
            expires_in=data.get("expires_in", 300),
            refresh_expires_in=data.get("refresh_expires_in", 1800),
            session_state=data.get("session_state", ""),
            scope=data.get("scope", "openid"),
            created_at=datetime.now(),
        )
        return self._tokens

    def _extract_form_action(self, html_content: str) -> Optional[str]:
        """Extract and decode form action URL from login page."""
        action_match = re.search(r'action="([^"]+)"', html_content)
        if action_match:
            action_url = html.unescape(action_match.group(1))
            if not action_url.startswith("http"):
                action_url = f"{self.config.sso_url}{action_url}"
            return action_url
        return None

    # =========================================================================
    # API REQUESTS
    # =========================================================================

    async def get_api(
        self,
        path: str,
        params: Optional[dict[str, str]] = None,
    ) -> httpx.Response:
        """Make authenticated GET request to PJN API."""
        await self._ensure_tokens()
        assert self._client is not None
        assert self._tokens is not None

        headers = {
            "Authorization": f"Bearer {self._tokens.access_token}",
            "Accept": "application/json",
            "User-Agent": self.config.user_agent,
            "Origin": self.config.portal_url,
        }

        return await self._client.get(
            f"{self.config.api_url}{path}",
            params=params,
            headers=headers,
        )

    async def _ensure_scw_session(self) -> None:
        """
        Ensure we have a valid SCW session.

        SCW uses its own OAuth flow (client_id=pjn-scw) separate from the portal.
        We must complete this OAuth flow to get a proper JSESSIONID that allows
        form submissions to work.

        The flow is:
        1. Access homePrivado.seam WITHOUT Bearer token
        2. SCW redirects to SSO with client_id=pjn-scw
        3. SSO sees we're already authenticated (from portal auth) and redirects back
        4. SCW establishes JSESSIONID cookie
        """
        await self._ensure_tokens()
        assert self._client is not None

        # Check if we already have a valid SCW session
        jsessionid = self._client.cookies.get("JSESSIONID")
        if jsessionid:
            # Already have session - but verify it's still valid
            # by checking if we can access a page without OAuth redirect
            return

        # Access homePrivado WITHOUT Bearer token to trigger SCW OAuth flow
        # The Keycloak cookies from portal auth will be used by SSO
        headers = {
            **self.DEFAULT_HEADERS,
            "Referer": f"{self.config.portal_url}/",
        }

        # Follow the OAuth redirect chain
        response = await self._client.get(
            f"{self.config.scw_url}/scw/homePrivado.seam",
            headers=headers,
            follow_redirects=True,  # Let httpx follow all redirects
        )

    async def get_scw(
        self,
        path: str,
        params: Optional[dict[str, str]] = None,
    ) -> httpx.Response:
        """Make authenticated GET request to SCW (Sistema de Consulta Web)."""
        await self._ensure_scw_session()
        assert self._client is not None

        headers = {
            **self.DEFAULT_HEADERS,
            "Sec-Fetch-Site": "same-origin",
            "Referer": f"{self.config.scw_url}/scw/homePrivado.seam",
        }

        return await self._client.get(
            f"{self.config.scw_url}/scw{path}",
            params=params,
            headers=headers,
            follow_redirects=True,
        )

    async def post_scw(
        self,
        path: str,
        data: dict[str, Any],
        referer: Optional[str] = None,
    ) -> httpx.Response:
        """Make authenticated POST request to SCW."""
        await self._ensure_scw_session()
        assert self._client is not None

        headers = {
            **self.DEFAULT_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": self.config.scw_url,
            "Sec-Fetch-Site": "same-origin",
            "Referer": referer or f"{self.config.scw_url}/scw/homePrivado.seam",
        }

        return await self._client.post(
            f"{self.config.scw_url}/scw{path}",
            data=data,
            headers=headers,
            follow_redirects=True,
        )

    async def post_scw_ajax(
        self,
        path: str,
        data: dict[str, Any],
        referer: Optional[str] = None,
    ) -> httpx.Response:
        """
        Make an AJAX POST request to SCW (RichFaces/JSF partial requests).

        Differs from post_scw() in that it:
        - Adds Faces-Request: partial/ajax header
        - Sets Accept: */* and Sec-Fetch-Dest: empty, Sec-Fetch-Mode: cors
        - Does NOT follow redirects (AJAX responses are XML, not HTML)
        """
        await self._ensure_scw_session()
        assert self._client is not None

        headers = {
            **self.DEFAULT_HEADERS,
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Faces-Request": "partial/ajax",
            "Origin": self.config.scw_url,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Referer": referer or f"{self.config.scw_url}/scw/homePrivado.seam",
        }

        return await self._client.post(
            f"{self.config.scw_url}/scw{path}",
            data=data,
            headers=headers,
            follow_redirects=False,
        )

    async def get_favoritos_page(self) -> httpx.Response:
        """Get the consultaListaFavoritos.seam page (Mis Expedientes)."""
        return await self.get_scw("/consultaListaFavoritos.seam")

    async def get_relacionados_page(self) -> httpx.Response:
        """
        Get the consultaListaRelacionados.seam page.

        This page shows expedientes where the user is related (AUTORIZADO NE or LETRADO).
        Initially displays role selection options, then expedientes after role is selected.
        """
        return await self.get_scw("/consultaListaRelacionados.seam")

    async def select_relacionados_profile(
        self,
        view_state: str,
        profile_index: int = 0,
        form_id: str = "j_idt76:j_idt78",
    ) -> httpx.Response:
        """
        Select a profile/role on the consultaListaRelacionados.seam page.

        The page displays role options like AUTORIZADO NE (index 0) and LETRADO (index 1).
        This method clicks the button for the specified profile.

        Args:
            view_state: JSF ViewState from the relacionados page
            profile_index: Index of the profile (0=AUTORIZADO NE, 1=LETRADO typically)
            form_id: The form ID (default: j_idt76:j_idt78)

        Returns:
            HTTP response with expedientes for the selected profile
        """
        await self._ensure_scw_session()
        assert self._client is not None

        # Build the button ID for this profile
        # Format: {form_id}:dataTablePerfiles:{profile_index}:btnConsultaExpedientesSAU
        button_id = f"{form_id}:dataTablePerfiles:{profile_index}:btnConsultaExpedientesSAU"

        import urllib.parse

        form_body = urllib.parse.urlencode([
            (form_id, form_id),
            (button_id, button_id),
            ("javax.faces.ViewState", view_state),
        ])

        page_url = f"{self.config.scw_url}/scw/consultaListaRelacionados.seam"

        headers = {
            **self.DEFAULT_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": self.config.scw_url,
            "Sec-Fetch-Site": "same-origin",
            "Referer": page_url,
            "Cache-Control": "max-age=0",
        }

        response = await self._client.post(
            page_url,
            content=form_body.encode("utf-8"),
            headers=headers,
            follow_redirects=True,
        )

        # PJN redirects to homePrivado.seam?cid=XXXX after profile selection.
        # Follow up by requesting consultaListaRelacionados.seam with the same
        # cid to get the actual expedientes list.
        final_url = str(response.url)
        if "homePrivado.seam" in final_url and "cid=" in final_url:
            cid_match = re.search(r'cid=(\d+)', final_url)
            if cid_match:
                cid = cid_match.group(1)
                response = await self.get_scw(
                    f"/consultaListaRelacionados.seam?cid={cid}"
                )

        return response

    async def fetch_relacionados_page(
        self,
        view_state: str,
        page_element_id: str,
        form_id: str = "tablaConsultaLista:tablaConsultaForm",
    ) -> httpx.Response:
        """
        Fetch a specific page of relacionados expedientes via RichFaces AJAX.

        Args:
            view_state: Current JSF ViewState value
            page_element_id: The pagination element ID
            form_id: The form ID (default: tablaConsultaLista:tablaConsultaForm)

        Returns:
            HTTP response with XML partial response containing expedientes HTML
        """
        await self._ensure_scw_session()
        assert self._client is not None

        form_data = {
            form_id: form_id,
            "javax.faces.ViewState": view_state,
            "javax.faces.source": page_element_id,
            "javax.faces.partial.event": "click",
            "javax.faces.partial.execute": f"{page_element_id} @component",
            "javax.faces.partial.render": "@component",
            "conversationPropagation": "join",
            "org.richfaces.ajax.component": page_element_id,
            page_element_id: page_element_id,
            "rfExt": "null",
            "AJAX:EVENTS_COUNT": "1",
            "javax.faces.partial.ajax": "true",
        }

        headers = {
            **self.DEFAULT_HEADERS,
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Faces-Request": "partial/ajax",
            "Origin": self.config.scw_url,
            "Referer": f"{self.config.scw_url}/scw/consultaListaRelacionados.seam",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
        }

        return await self._client.post(
            f"{self.config.scw_url}/scw/consultaListaRelacionados.seam",
            data=form_data,
            headers=headers,
            follow_redirects=False,
        )

    async def view_expediente_detail(
        self,
        row_index: int,
        view_state: str,
        form_id: str = "j_idt166:tablaConsultaForm",
        table_part: str = "j_idt172",
        button_suffix: str = "j_idt223",
        source_page: str = "consultaListaFavoritos",
    ) -> httpx.Response:
        """
        Navigate to expediente detail by submitting the JSF form.

        This replicates the mojarra.jsfcljs form submission that happens
        when clicking the "view" button on an expediente row.

        Args:
            row_index: Index of the expediente row (0-based)
            view_state: JSF ViewState from the source page
            form_id: The form ID (default: j_idt166:tablaConsultaForm)
            table_part: The table component ID (default: j_idt172)
            button_suffix: The button ID suffix (default: j_idt223)
            source_page: Source page name without .seam (default: consultaListaFavoritos)

        Returns:
            HTTP response with expediente detail page
        """
        await self._ensure_scw_session()
        assert self._client is not None

        # Build the button ID for this row
        # Format: {form_id}:{table_part}:dataTable:{row_index}:{button_suffix}
        button_id = f"{form_id}:{table_part}:dataTable:{row_index}:{button_suffix}"

        # JSF form data - order matters for some JSF implementations
        # Use list of tuples to preserve order
        import urllib.parse

        form_body = urllib.parse.urlencode([
            (form_id, form_id),
            ("javax.faces.ViewState", view_state),
            (button_id, button_id),
        ])

        page_url = f"{self.config.scw_url}/scw/{source_page}.seam"

        headers = {
            **self.DEFAULT_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": self.config.scw_url,
            "Sec-Fetch-Site": "same-origin",
            "Referer": page_url,
            "Cache-Control": "max-age=0",
        }

        return await self._client.post(
            page_url,
            content=form_body.encode("utf-8"),
            headers=headers,
            follow_redirects=True,
        )

    async def download_document(
        self,
        document_url: str,
    ) -> httpx.Response:
        """
        Download a document (PDF) from SCW.

        Args:
            document_url: The document URL path (e.g., "/scw/viewer.seam?id=...&tipoDoc=despacho&download=true")

        Returns:
            HTTP response with PDF content (response.content contains the bytes)
        """
        await self._ensure_scw_session()
        assert self._client is not None

        # Build full URL if needed
        if document_url.startswith("/"):
            full_url = f"{self.config.scw_url}{document_url}"
        else:
            full_url = document_url

        headers = {
            **self.DEFAULT_HEADERS,
            "Accept": "application/pdf,*/*",
            "Referer": f"{self.config.scw_url}/scw/expediente.seam",
        }

        return await self._client.get(
            full_url,
            headers=headers,
            follow_redirects=True,
        )

    async def fetch_actuaciones_page(
        self,
        cid: str,
        view_state: str,
        page_element_id: str,
    ) -> httpx.Response:
        """
        Fetch a specific page of actuaciones via RichFaces AJAX.

        Args:
            cid: Conversation ID from the expediente page URL
            view_state: Current JSF ViewState value
            page_element_id: The pagination element ID (e.g., "expediente:j_idt217:j_idt227:1:j_idt229")

        Returns:
            HTTP response with XML partial response containing actuaciones HTML
        """
        await self._ensure_scw_session()
        assert self._client is not None

        # RichFaces AJAX form data for pagination
        form_data = {
            "expediente": "expediente",
            "expediente:j_idt99:j_idt105": "expediente:j_idt99:j_idt105",
            "javax.faces.ViewState": view_state,
            "expediente:j_idt99:j_idt100_collapsed": "false",
            "expediente:expedienteTab-value": "actuaciones",
            "expediente:checkBoxOtrasActuacionesId": "on",
            "javax.faces.source": page_element_id,
            "javax.faces.partial.execute": f"{page_element_id} @component",
            "javax.faces.partial.render": "@component",
            "org.richfaces.ajax.component": page_element_id,
            page_element_id: page_element_id,
            "rfExt": "null",
            "AJAX:EVENTS_COUNT": "1",
            "javax.faces.partial.ajax": "true",
        }

        headers = {
            **self.DEFAULT_HEADERS,
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Faces-Request": "partial/ajax",
            "Origin": self.config.scw_url,
            "Referer": f"{self.config.scw_url}/scw/expediente.seam?cid={cid}",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
        }

        return await self._client.post(
            f"{self.config.scw_url}/scw/expediente.seam",
            data=form_data,
            headers=headers,
            follow_redirects=False,
        )

    async def fetch_intervinientes_tab(
        self,
        cid: str,
        view_state: str,
    ) -> httpx.Response:
        """
        Fetch the Intervinientes tab content via RichFaces AJAX.

        This mimics the browser's AJAX call when clicking the "Intervinientes" tab.

        Args:
            cid: Conversation ID from the expediente page URL
            view_state: Current JSF ViewState value

        Returns:
            HTTP response with XML partial response containing intervinientes HTML
        """
        await self._ensure_scw_session()
        assert self._client is not None

        # RichFaces AJAX form data
        form_data = {
            "expediente": "expediente",
            "expediente:j_idt99:j_idt105": "expediente:j_idt99:j_idt105",
            "javax.faces.ViewState": view_state,
            "expediente:j_idt99:j_idt100_collapsed": "false",
            "expediente:expedienteTab-value": "intervinientes",
            "expediente:checkBoxOtrasActuacionesId": "on",
            "javax.faces.source": "expediente:j_idt270",
            "javax.faces.partial.execute": "expediente:j_idt270 @component",
            "javax.faces.partial.render": "@component",
            "org.richfaces.ajax.component": "expediente:j_idt270",
            "expediente:j_idt270": "expediente:j_idt270",
            "rfExt": "null",
            "AJAX:EVENTS_COUNT": "1",
            "javax.faces.partial.ajax": "true",
        }

        headers = {
            **self.DEFAULT_HEADERS,
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Faces-Request": "partial/ajax",
            "Origin": self.config.scw_url,
            "Referer": f"{self.config.scw_url}/scw/expediente.seam?cid={cid}",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
        }

        return await self._client.post(
            f"{self.config.scw_url}/scw/expediente.seam",
            data=form_data,
            headers=headers,
            follow_redirects=False,
        )

    async def _ensure_tokens(self) -> None:
        """Ensure we have valid tokens, refreshing if needed."""
        if self._tokens is None:
            raise AuthenticationError("Not authenticated - call authenticate() first")

        if self._tokens.is_expired:
            if self._tokens.is_refresh_expired:
                raise TokenError("Session expired - re-authentication required")
            await self.refresh_tokens()

    # =========================================================================
    # PROPERTIES
    # =========================================================================

    @property
    def tokens(self) -> Optional[TokenSet]:
        """Get current tokens."""
        return self._tokens

    @property
    def is_authenticated(self) -> bool:
        """Check if client has valid authentication."""
        return self._tokens is not None and not self._tokens.is_refresh_expired

    def get_cookies(self) -> dict[str, str]:
        """Get all cookies as a dictionary."""
        if self._client is None:
            return {}
        return dict(self._client.cookies)

    def get_user_info_from_token(self) -> Optional[UserInfo]:
        """Decode user info from ID token."""
        if self._tokens is None:
            return None

        try:
            import base64
            import json

            # JWT is base64url encoded, split by dots
            parts = self._tokens.id_token.split(".")
            if len(parts) != 3:
                return None

            # Decode payload (second part)
            payload = parts[1]
            # Add padding if needed
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += "=" * padding

            decoded = base64.urlsafe_b64decode(payload)
            claims = json.loads(decoded)
            return UserInfo.from_token_claims(claims)
        except Exception:
            return None

    # =========================================================================
    # CAPTCHA PROXY
    # =========================================================================

    async def get_captcha_challenge(self, sitekey: str = "SCW") -> dict[str, Any]:
        """
        Get captcha challenge from PJN captcha server.

        Returns a dict with:
        - csid: session ID for the captcha
        - d: base64-encoded JPEG image data
        - cto: timeout in seconds
        """
        await self._ensure_tokens()
        assert self._client is not None
        assert self._tokens is not None

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._tokens.access_token}",
            "User-Agent": self.config.user_agent,
            "Referer": "https://scw.pjn.gov.ar/",
            "Origin": "https://scw.pjn.gov.ar",
        }

        # Get initial challenge - follow redirects
        response = await self._client.get(
            f"https://captcha.pjn.gov.ar/api/challenge?sitekey={sitekey}",
            headers=headers,
            follow_redirects=True,
        )

        if response.status_code != 200:
            raise NetworkError(
                f"Failed to get captcha challenge: {response.status_code}",
                {"response": response.text[:500]},
            )

        return response.json()

    async def submit_captcha_response(
        self, sitekey: str, response_text: str, csid: str
    ) -> dict[str, Any]:
        """
        Submit captcha response to PJN captcha server.

        Args:
            sitekey: The captcha sitekey (e.g., "SCW")
            response_text: The user's answer to the captcha challenge
            csid: The captcha session ID from get_captcha_challenge

        Returns:
            dict with validation result including token if successful
        """
        await self._ensure_tokens()
        assert self._client is not None
        assert self._tokens is not None

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._tokens.access_token}",
            "User-Agent": self.config.user_agent,
            "Referer": "https://scw.pjn.gov.ar/",
            "Origin": "https://scw.pjn.gov.ar",
        }

        response = await self._client.get(
            f"https://captcha.pjn.gov.ar/api/challenge/response",
            params={
                "sitekey": sitekey,
                "response": response_text,
                "csid": csid,
            },
            headers=headers,
            follow_redirects=True,
        )

        if response.status_code != 200:
            raise NetworkError(
                f"Failed to submit captcha response: {response.status_code}",
                {"response": response.text[:500]},
            )

        return response.json()
