"""
SCW Public Search Service — search ANY federal court case via PJN's SCW.

Authenticated PJN users can search the SCW public search without captcha.
Supports search by expediente number and by party name (parte) across all
28 PJN jurisdictions.
"""

import logging
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional

import httpx

from .exceptions import SearchError
from .http_client import PJNHttpClient
from .models import SCWResult
from .parsers import SCWSearchResultsParser

logger = logging.getLogger(__name__)

SCW_BASE = "https://scw.pjn.gov.ar"


@dataclass
class SCWSearchResult:
    """Container for SCW search results."""

    results: list[SCWResult] = field(default_factory=list)
    total: int = 0
    jurisdiction_code: str = ""
    search_type: str = ""


class SCWPublicSearchService:
    """
    Orchestrates JSF form interactions for SCW public search.

    Takes an already-authenticated PJNHttpClient and performs the multi-step
    JSF form interactions needed for public case search.
    """

    def __init__(self, client: PJNHttpClient):
        self._client = client
        self._results_parser = SCWSearchResultsParser()

    async def search_by_numero(
        self,
        numero: str,
        anio: str,
        jurisdiction_code: str = "0",
    ) -> SCWSearchResult:
        """
        Search SCW by expediente number.

        This is the simpler flow — direct form POST, no AJAX needed.

        Args:
            numero: Expediente number (e.g., "190")
            anio: Year (e.g., "2008")
            jurisdiction_code: Jurisdiction/camara code (e.g., "0" for CSJ)

        Returns:
            SCWSearchResult with matching expedientes
        """
        cid, view_state = await self._navigate_to_public_search()

        form_data = {
            "formPublica": "formPublica",
            "formPublica:expedienteTab-value": "porExpediente",
            "formPublica:camaraNumAni": jurisdiction_code,
            "formPublica:numero": numero,
            "formPublica:anio": anio,
            "formPublica:buscarPorNumeroButton": "formPublica:buscarPorNumeroButton",
            "javax.faces.ViewState": view_state,
            "conversationPropagation": "join",
        }

        referer = f"{SCW_BASE}/scw/home.seam?cid={cid}"
        response = await self._client.post_scw(
            "/home.seam", data=form_data, referer=referer
        )

        results = self._results_parser.parse_results(response.text, str(response.url))

        return SCWSearchResult(
            results=results,
            total=len(results),
            jurisdiction_code=jurisdiction_code,
            search_type="numero",
        )

    async def search_by_parte(
        self,
        parte: str,
        jurisdiction_code: str = "0",
    ) -> SCWSearchResult:
        """
        Search SCW by party name.

        Requires 2 AJAX calls for non-CSJ jurisdictions (tab switch + jurisdiction set),
        or 1 AJAX call for CSJ (tab switch only, since CSJ is the default camara).

        Args:
            parte: Party name to search (e.g., "arrieta")
            jurisdiction_code: Jurisdiction/camara code (e.g., "1" for CIV)

        Returns:
            SCWSearchResult with matching expedientes
        """
        cid, view_state = await self._navigate_to_public_search()

        # AJAX 1: Switch to porParte tab (loads JSF state for parte fields)
        view_state = await self._ajax_tab_switch(cid, view_state)

        # AJAX 2: Set jurisdiction (only needed for non-CSJ, but harmless for CSJ)
        if jurisdiction_code != "0":
            view_state = await self._ajax_set_jurisdiction(
                cid, view_state, jurisdiction_code
            )

        # Submit search by parte (regular form POST)
        form_data = {
            "formPublica": "formPublica",
            "formPublica:expedienteTab-value": "porParte",
            "formPublica:camaraNumAni": "",
            "formPublica:numero": "",
            "formPublica:anio": "",
            "formPublica:camaraPartes": jurisdiction_code,
            "formPublica:tipo": "",
            "formPublica:nomIntervParte": parte,
            "formPublica:buscarPorParteButton": "Consultar",
            "javax.faces.ViewState": view_state,
        }

        referer = f"{SCW_BASE}/scw/home.seam?cid={cid}"
        response = await self._client.post_scw(
            "/home.seam", data=form_data, referer=referer
        )

        results = self._results_parser.parse_results(response.text, str(response.url))

        return SCWSearchResult(
            results=results,
            total=len(results),
            jurisdiction_code=jurisdiction_code,
            search_type="parte",
        )

    async def search_and_view_detail(
        self,
        search_type: str,
        row_index: int,
        jurisdiction_code: str = "0",
        numero: str = "",
        anio: str = "",
        parte: str = "",
    ) -> tuple[str, str]:
        """
        Re-execute a search and navigate to the detail page for a specific result.

        Returns:
            Tuple of (detail_html, detail_url)
        """
        # Step 1: Execute the search to get a live results page
        response = await self._execute_search(
            search_type, jurisdiction_code, numero, anio, parte
        )

        results_html = response.text
        results_url = str(response.url)

        # Step 2: Extract ViewState and navigation button for the row
        view_state = self._extract_view_state(results_html)
        if not view_state:
            raise SearchError(
                "Could not extract ViewState from results page",
                {"url": results_url},
            )

        form_id, button_id = self._results_parser.extract_result_navigation(
            results_html, row_index
        )
        if not button_id:
            raise SearchError(
                f"Could not find navigation button for result {row_index}",
                {"url": results_url},
            )

        # Step 3: Submit JSF form to navigate to expediente detail
        detail_response = await self._click_result_row(
            results_url, view_state, form_id, button_id
        )

        return detail_response.text, str(detail_response.url)

    # =========================================================================
    # INTERNAL METHODS
    # =========================================================================

    async def _execute_search(
        self,
        search_type: str,
        jurisdiction_code: str,
        numero: str,
        anio: str,
        parte: str,
    ) -> httpx.Response:
        """Execute a search and return the raw httpx response."""
        cid, view_state = await self._navigate_to_public_search()
        referer = f"{SCW_BASE}/scw/home.seam?cid={cid}"

        if search_type == "numero":
            form_data = {
                "formPublica": "formPublica",
                "formPublica:expedienteTab-value": "porExpediente",
                "formPublica:camaraNumAni": jurisdiction_code,
                "formPublica:numero": numero,
                "formPublica:anio": anio,
                "formPublica:buscarPorNumeroButton": "formPublica:buscarPorNumeroButton",
                "javax.faces.ViewState": view_state,
                "conversationPropagation": "join",
            }
        else:
            view_state = await self._ajax_tab_switch(cid, view_state)
            if jurisdiction_code != "0":
                view_state = await self._ajax_set_jurisdiction(
                    cid, view_state, jurisdiction_code
                )
            form_data = {
                "formPublica": "formPublica",
                "formPublica:expedienteTab-value": "porParte",
                "formPublica:camaraNumAni": "",
                "formPublica:numero": "",
                "formPublica:anio": "",
                "formPublica:camaraPartes": jurisdiction_code,
                "formPublica:tipo": "",
                "formPublica:nomIntervParte": parte,
                "formPublica:buscarPorParteButton": "Consultar",
                "javax.faces.ViewState": view_state,
            }

        return await self._client.post_scw(
            "/home.seam", data=form_data, referer=referer
        )

    async def _click_result_row(
        self,
        results_url: str,
        view_state: str,
        form_id: str,
        button_id: str,
    ) -> httpx.Response:
        """Submit JSF form to navigate from search results to expediente detail."""
        await self._client._ensure_scw_session()
        assert self._client._client is not None

        form_body = urllib.parse.urlencode([
            (form_id, form_id),
            ("javax.faces.ViewState", view_state),
            (button_id, button_id),
        ])

        # Extract page URL (without query params — cid is in the session)
        parsed = urllib.parse.urlparse(results_url)
        page_url = f"{self._client.config.scw_url}{parsed.path}"

        headers = {
            **self._client.DEFAULT_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": self._client.config.scw_url,
            "Sec-Fetch-Site": "same-origin",
            "Referer": results_url,
            "Cache-Control": "max-age=0",
        }

        return await self._client._client.post(
            page_url,
            content=form_body.encode("utf-8"),
            headers=headers,
            follow_redirects=True,
        )

    async def _navigate_to_public_search(self) -> tuple[str, str]:
        """
        Navigate to the SCW public search form (home.seam).

        Uses consultaListaRelacionados.seam with actionOutcome=/home.xhtml
        to get a fresh public search form with a conversation ID.

        Returns:
            Tuple of (cid, view_state)
        """
        response = await self._client.get_scw(
            "/consultaListaRelacionados.seam",
            params={"actionOutcome": "/home.xhtml"},
        )

        view_state = self._extract_view_state(response.text)
        cid = self._extract_cid(str(response.url))

        if not view_state:
            raise SearchError(
                "Could not extract ViewState from public search form",
                {"url": str(response.url)},
            )
        if not cid:
            raise SearchError(
                "Could not extract conversation ID from public search URL",
                {"url": str(response.url)},
            )

        return cid, view_state

    async def _ajax_tab_switch(self, cid: str, view_state: str) -> str:
        """
        AJAX call to switch to porParte tab.

        This loads the JSF state for parte fields on the server side.
        Returns the updated ViewState.
        """
        referer = f"{SCW_BASE}/scw/home.seam?cid={cid}"

        data = {
            "formPublica": "formPublica",
            "formPublica:expedienteTab-value": "porParte",
            "formPublica:camaraNumAni": "",
            "formPublica:numero": "",
            "formPublica:anio": "",
            "javax.faces.ViewState": view_state,
            "javax.faces.source": "formPublica:porParte",
            "javax.faces.partial.execute": "formPublica:porParte @component",
            "javax.faces.partial.render": "@component",
            "org.richfaces.ajax.component": "formPublica:porParte",
            "formPublica:porParte": "formPublica:porParte",
            "rfExt": "null",
            "AJAX:EVENTS_COUNT": "1",
            "javax.faces.partial.ajax": "true",
        }

        response = await self._client.post_scw_ajax(
            "/home.seam", data=data, referer=referer
        )

        new_vs = self._extract_view_state_from_ajax(response.text)
        if new_vs:
            return new_vs

        logger.warning("No updated ViewState in tab switch response, using original")
        return view_state

    async def _ajax_set_jurisdiction(
        self, cid: str, view_state: str, camara: str
    ) -> str:
        """
        AJAX call to set jurisdiction/camara on the parte search form.

        Triggers server-side state update for the selected jurisdiction.
        Returns the updated ViewState.
        """
        referer = f"{SCW_BASE}/scw/home.seam?cid={cid}"

        data = {
            "formPublica": "formPublica",
            "formPublica:expedienteTab-value": "porParte",
            "formPublica:camaraNumAni": "",
            "formPublica:numero": "",
            "formPublica:anio": "",
            "formPublica:camaraPartes": camara,
            "formPublica:tipo": "",
            "formPublica:nomIntervParte": "",
            "javax.faces.ViewState": view_state,
            "javax.faces.source": "formPublica:camaraPartes",
            "javax.faces.partial.event": "change",
            "javax.faces.partial.execute": "formPublica:camaraPartes formPublica:camaraPartes",
            "javax.faces.partial.render": "formPublica:leyenda formPublica:tipo",
            "javax.faces.behavior.event": "change",
            "AJAX:EVENTS_COUNT": "1",
            "rfExt": "null",
            "javax.faces.partial.ajax": "true",
        }

        response = await self._client.post_scw_ajax(
            "/home.seam", data=data, referer=referer
        )

        new_vs = self._extract_view_state_from_ajax(response.text)
        if new_vs:
            return new_vs

        logger.warning(
            "No updated ViewState in jurisdiction response, using original"
        )
        return view_state

    # =========================================================================
    # UTILITIES
    # =========================================================================

    @staticmethod
    def _extract_view_state(html: str) -> Optional[str]:
        """Extract JSF ViewState from HTML form."""
        match = re.search(
            r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"', html
        )
        return match.group(1) if match else None

    @staticmethod
    def _extract_view_state_from_ajax(xml: str) -> Optional[str]:
        """Extract ViewState from JSF AJAX XML response."""
        # Try CDATA format first (most common in AJAX responses)
        match = re.search(
            r'<update id="javax\.faces\.ViewState"><!\[CDATA\[([^\]]+)\]\]>',
            xml,
        )
        if match:
            return match.group(1)

        # Fall back to standard input format
        match = re.search(
            r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"', xml
        )
        return match.group(1) if match else None

    @staticmethod
    def _extract_cid(url: str) -> Optional[str]:
        """Extract conversation ID from URL."""
        match = re.search(r"cid=(\d+)", url)
        return match.group(1) if match else None
