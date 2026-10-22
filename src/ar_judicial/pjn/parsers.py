"""HTML parsers for PJN service.

Extracts data from SCW (Sistema de Consulta Web) pages.
Uses BeautifulSoup with lxml for reliable HTML parsing.
Regex is only used for AJAX XML/CDATA extraction (well-formed XML)
and for extracting structured JSF IDs from onclick handlers.
"""

import re
from typing import Optional

from bs4 import BeautifulSoup

from .models import (
    Actuacion,
    ActuacionesList,
    CaptchaChallenge,
    Expediente,
    ExpedienteDetail,
    ExpedienteList,
    Fiscal,
    Interviniente,
    IntervinientesList,
    Letrado,
    RelacionadosProfile,
    RelacionadosPage,
    SCWResult,
)


# =============================================================================
# SHARED HELPERS
# =============================================================================


def _bs(html: str) -> BeautifulSoup:
    """Create a BeautifulSoup instance with lxml parser."""
    return BeautifulSoup(html, "lxml")


def _extract_view_state(soup: BeautifulSoup) -> str:
    """Extract JSF ViewState from a parsed page."""
    tag = soup.find("input", {"name": "javax.faces.ViewState"})
    return tag.get("value", "") if tag else ""


def _extract_cdata_blocks(xml_content: str) -> list[str]:
    """Extract all CDATA blocks from RichFaces AJAX XML response."""
    return re.findall(r'<!\[CDATA\[(.*?)\]\]>', xml_content, re.DOTALL)


def _extract_main_cdata(xml_content: str) -> Optional[str]:
    """
    Extract the main HTML content from an AJAX CDATA response.

    RichFaces AJAX responses contain multiple CDATA blocks (HTML content,
    ViewState hash, etc.). This removes the ViewState block and returns
    the largest remaining block (the main HTML content).
    """
    # Remove ViewState update block
    cleaned = re.sub(
        r'<update id="javax\.faces\.ViewState"><!\[CDATA\[[^\]]*\]\]></update>',
        '',
        xml_content,
    )
    blocks = _extract_cdata_blocks(cleaned)
    if not blocks:
        return None
    return max(blocks, key=len)


def _extract_view_state_from_ajax(xml_content: str) -> Optional[str]:
    """Extract updated ViewState from RichFaces AJAX XML response."""
    match = re.search(
        r'<update id="javax\.faces\.ViewState"><!\[CDATA\[([^\]]+)\]\]>',
        xml_content,
    )
    return match.group(1) if match else None


# =============================================================================
# CAPTCHA PARSER
# =============================================================================


class CaptchaParser:
    """Parser for extracting captcha challenge from SCW pages."""

    CAPTCHA_URL = "https://captcha.pjn.gov.ar/api/init.js"
    DEFAULT_SITE_KEY = "SCW"

    def parse(self, html_content: str) -> Optional[CaptchaChallenge]:
        soup = _bs(html_content)

        captcha_div = (
            soup.find("div", class_=re.compile(r'pjn-captcha'))
            or soup.find("div", attrs={"data-sitekey": True})
        )
        if not captcha_div:
            return None

        site_key = captcha_div.get("data-sitekey", self.DEFAULT_SITE_KEY)

        form = soup.find("form", id="formPublica")
        form_action = form.get("action", "/scw/home.seam") if form else "/scw/home.seam"

        view_state = _extract_view_state(soup)

        script = soup.find("script", src=re.compile(r'captcha\.pjn\.gov\.ar'))
        captcha_url = script.get("src", self.CAPTCHA_URL) if script else self.CAPTCHA_URL

        return CaptchaChallenge(
            site_key=site_key,
            captcha_url=captcha_url,
            form_action=form_action,
            view_state=view_state,
            captcha_div_html=str(captcha_div),
        )


# =============================================================================
# SEARCH FORM PARSER
# =============================================================================


class SearchFormParser:
    """Parser for extracting search form data from SCW pages."""

    def extract_jurisdictions(self, html_content: str) -> list[dict]:
        soup = _bs(html_content)
        jurisdictions = []

        select = soup.find("select", id="formPublica:camaraNumAni")
        if not select:
            return jurisdictions

        for option in select.find_all("option"):
            value = option.get("value", "")
            if not value:
                continue
            text = option.get_text(strip=True)
            parts = text.split(" - ", 1)
            short_code = parts[0].strip() if len(parts) == 2 else ""
            name = parts[1].strip() if len(parts) == 2 else text
            jurisdictions.append({"code": value, "short_code": short_code, "name": name})

        return jurisdictions

    def extract_form_fields(self, html_content: str) -> dict:
        soup = _bs(html_content)
        fields = {}

        vs = _extract_view_state(soup)
        if vs:
            fields["javax.faces.ViewState"] = vs

        form_input = soup.find("input", {"name": "formPublica"})
        if form_input:
            fields["formPublica"] = form_input.get("value", "")

        tab_input = soup.find("input", id="formPublica:expedienteTab-value")
        if tab_input:
            fields["formPublica:expedienteTab-value"] = tab_input.get("value", "")

        return fields


# =============================================================================
# ERROR PARSER
# =============================================================================


class ErrorParser:
    """Parser for extracting error messages from SCW pages."""

    def extract_error(self, html_content: str) -> Optional[str]:
        soup = _bs(html_content)

        msg = soup.find("span", class_=re.compile(r'ui-messages-.*-summary'))
        if msg:
            return msg.get_text(strip=True)

        msg = soup.find("span", id="input-error")
        if msg:
            return msg.get_text(strip=True)

        msg = soup.find("div", class_=re.compile(r'error', re.I))
        if msg and msg.get_text(strip=True):
            return msg.get_text(strip=True)

        return None


# =============================================================================
# FAVORITOS PARSER (EXPEDIENTES TABLE)
# =============================================================================


class FavoritosParser:
    """Parser for extracting expedientes from consultaListaFavoritos.seam page."""

    def parse(self, html_content: str) -> ExpedienteList:
        soup = _bs(html_content)
        expedientes: list[Expediente] = []

        # Find the expedientes data table (ID ends with ":dataTable" or is "dataTable").
        # Must not match "dataTablePerfiles" which is the profile selection table.
        table = soup.find("table", id=re.compile(r'dataTable$'))
        if table:
            tbody = table.find("tbody")
            if tbody:
                for row in tbody.find_all("tr"):
                    columns = row.find_all("td", class_="column")
                    if len(columns) < 5:
                        continue

                    # Extract row_index from any element ID containing "dataTable:N:"
                    row_index = None
                    for tag in row.find_all(True, id=re.compile(r'dataTable:\d+')):
                        match = re.search(r'dataTable:(\d+)', tag.get("id", ""))
                        if match:
                            row_index = int(match.group(1))
                            break

                    if row_index is None:
                        continue

                    # Extract internal ID from onclick handler JSON
                    internal_id = None
                    for tag in row.find_all(True, onclick=True):
                        id_match = re.search(r'"id":"(\d+)"', tag.get("onclick", ""))
                        if id_match:
                            internal_id = id_match.group(1)
                            break

                    expedientes.append(Expediente(
                        numero=columns[0].get_text(strip=True),
                        dependencia=columns[1].get_text(strip=True),
                        caratula=columns[2].get_text(strip=True),
                        situacion=columns[3].get_text(strip=True),
                        ultima_actualizacion=columns[4].get_text(strip=True),
                        row_index=row_index,
                        internal_id=internal_id,
                    ))

        # Extract total count
        total_count = len(expedientes)
        total_match = re.search(
            r'Se han encontrado un total de (\d+) expediente',
            html_content,
        )
        if total_match:
            total_count = int(total_match.group(1))

        # Parse pagination
        current_page = 1
        total_pages = 1

        active_li = soup.find("li", class_="active")
        if active_li:
            span = active_li.find("span")
            if span and span.get_text(strip=True).isdigit():
                current_page = int(span.get_text(strip=True))

        page_numbers = []
        for li in soup.find_all("li"):
            a = li.find("a")
            if a:
                span = a.find("span")
                if span and span.get_text(strip=True).isdigit():
                    page_numbers.append(int(span.get_text(strip=True)))
        if page_numbers:
            total_pages = max(page_numbers)
        if current_page > total_pages:
            total_pages = current_page

        view_state = _extract_view_state(soup)

        return ExpedienteList(
            expedientes=expedientes,
            total_count=total_count,
            current_page=current_page,
            total_pages=total_pages,
            view_state=view_state,
        )

    def extract_form_ids(self, html_content: str) -> dict:
        """
        Extract JSF form IDs needed for navigation.

        Returns dict with form_id, table_part, button_suffix.
        These are encoded in onclick handlers like:
        'formId:tablePart:dataTable:rowIndex:buttonSuffix'
        """
        soup = _bs(html_content)

        for tag in soup.find_all(True, onclick=re.compile(r'dataTable:\d+')):
            onclick = tag.get("onclick", "")
            match = re.search(r"'([^']+):([^':]+):dataTable:(\d+):([\w]+)", onclick)
            if match:
                return {
                    "form_id": match.group(1),
                    "table_part": match.group(2),
                    "button_suffix": match.group(4),
                }

        # Fallback: extract form ID from element
        form = soup.find(True, id=re.compile(r'tablaConsultaForm'))
        form_id = form.get("id", "") if form else ""
        return {"form_id": form_id, "table_part": "", "button_suffix": ""}


# =============================================================================
# EXPEDIENTE DETAIL PARSER
# =============================================================================


class ExpedienteDetailParser:
    """Parser for extracting data from expediente detail page."""

    def parse_datos_generales(self, html_content: str) -> Optional[ExpedienteDetail]:
        soup = _bs(html_content)

        numero = ""
        for label in soup.find_all("label"):
            if "Expediente:" in label.get_text():
                parent = label.find_parent("div")
                if parent:
                    sibling_div = parent.find_next_sibling("div")
                    if sibling_div:
                        span = sibling_div.find("span")
                        if span:
                            numero = span.get_text(strip=True)
                break

        jurisdiccion = ""
        tag = soup.find(True, id=re.compile(r'detailCamera'))
        if tag:
            jurisdiccion = tag.get_text(strip=True)

        dependencia = ""
        tag = soup.find(True, id=re.compile(r'detailDependencia'))
        if tag:
            dependencia = tag.get_text(strip=True)

        situacion = ""
        tag = soup.find(True, id=re.compile(r'detailSituation'))
        if tag:
            situacion = tag.get_text(strip=True)

        caratula = ""
        tag = soup.find(True, id=re.compile(r'detailCover'))
        if tag:
            caratula = tag.get_text(strip=True)

        if not numero:
            return None

        return ExpedienteDetail(
            numero=numero,
            jurisdiccion=jurisdiccion,
            dependencia=dependencia,
            situacion=situacion,
            caratula=caratula,
        )

    def extract_view_state(self, html_content: str) -> Optional[str]:
        soup = _bs(html_content)
        vs = _extract_view_state(soup)
        return vs if vs else None

    def extract_cid(self, url: str) -> Optional[str]:
        match = re.search(r'cid=(\d+)', url)
        return match.group(1) if match else None

    def parse_actuaciones(self, html_content: str) -> ActuacionesList:
        soup = _bs(html_content)
        actuaciones: list[Actuacion] = []

        table = soup.find("table", id="expediente:action-table")
        if not table:
            return ActuacionesList(actuaciones=[], current_page=1, total_pages=1)

        tbody = table.find("tbody")
        if not tbody:
            return ActuacionesList(actuaciones=[], current_page=1, total_pages=1)

        for row in tbody.find_all("tr"):
            doc_download_url = None
            doc_view_url = None
            doc_tipo = None

            for a in row.find_all("a", href=re.compile(r'/scw/viewer\.seam')):
                href = a.get("href", "").replace("&amp;", "&")
                if "download=true" in href:
                    doc_download_url = href
                    tipo_match = re.search(r'tipoDoc=([^&"]+)', href)
                    if tipo_match:
                        doc_tipo = tipo_match.group(1)
                elif a.find("i", class_=re.compile(r'fa-eye')):
                    doc_view_url = href
                    if not doc_tipo:
                        tipo_match = re.search(r'tipoDoc=([^&"]+)', href)
                        if tipo_match:
                            doc_tipo = tipo_match.group(1)

            oficina = ""
            office_span = row.find(True, id=re.compile(r'officeColumn'))
            if office_span:
                oficina = office_span.get_text(strip=True)

            fecha = ""
            tipo = ""
            descripcion = ""
            for sr_span in row.find_all("span", class_="sr-only"):
                label = sr_span.get_text(strip=True)
                next_span = sr_span.find_next_sibling("span")
                if not next_span:
                    continue
                value = next_span.get_text(strip=True)
                if "Fecha:" in label:
                    fecha = value
                elif "Tipo actuacion:" in label:
                    tipo = value
                elif "Detalle:" in label:
                    descripcion = value

            fojas = None
            fojas_div = row.find("div", class_=re.compile(r'text-center'))
            if fojas_div:
                fojas_span = fojas_div.find("span")
                if fojas_span:
                    text = fojas_span.get_text(strip=True)
                    if re.match(r'\d+\s*/\s*\d+', text):
                        fojas = text

            if fecha and tipo:
                actuaciones.append(Actuacion(
                    oficina=oficina,
                    fecha=fecha,
                    tipo=tipo,
                    descripcion=descripcion,
                    fojas=fojas,
                    documento_url=doc_view_url,
                    documento_download_url=doc_download_url,
                    documento_tipo=doc_tipo,
                ))

        current_page, total_pages = self._parse_actuaciones_pagination(soup)

        return ActuacionesList(
            actuaciones=actuaciones,
            current_page=current_page,
            total_pages=total_pages,
        )

    def _parse_actuaciones_pagination(self, soup: BeautifulSoup) -> tuple[int, int]:
        current_page = 1
        total_pages = 1

        pagination_div = soup.find("div", id=re.compile(r'expediente:j_idt\d+:divPagesAct'))
        if not pagination_div:
            return current_page, total_pages

        active_li = pagination_div.find("li", class_="active")
        if active_li:
            span = active_li.find("span")
            if span and span.get_text(strip=True).isdigit():
                current_page = int(span.get_text(strip=True))

        page_numbers = []
        for span in pagination_div.find_all("span"):
            text = span.get_text(strip=True)
            if text.isdigit():
                page_numbers.append(int(text))
        if page_numbers:
            total_pages = max(page_numbers)

        return current_page, total_pages

    def extract_actuaciones_page_ids(self, html_content: str) -> dict[int, str]:
        soup = _bs(html_content)
        page_ids: dict[int, str] = {}

        pagination_div = soup.find("div", id=re.compile(r'expediente:j_idt\d+:divPagesAct'))
        if not pagination_div:
            return page_ids

        for a in pagination_div.find_all("a", id=re.compile(r'expediente:j_idt\d+:j_idt\d+:\d+:j_idt\d+')):
            span = a.find("span")
            if span and span.get_text(strip=True).isdigit():
                page_num = int(span.get_text(strip=True))
                page_ids[page_num] = a.get("id", "")

        return page_ids

    def extract_siguiente_id(self, html_content: str) -> Optional[str]:
        """Extract the "Siguiente" (Next page) element ID from actuaciones pagination."""
        soup = _bs(html_content)

        siguiente_span = soup.find("span", title="Siguiente")
        if siguiente_span:
            parent_a = siguiente_span.find_parent("a")
            if parent_a and parent_a.get("id"):
                return parent_a.get("id")

        return None

    def parse_actuaciones_from_ajax(self, xml_content: str) -> ActuacionesList:
        html = _extract_main_cdata(xml_content)
        if not html:
            return ActuacionesList(actuaciones=[], current_page=1, total_pages=1)
        return self.parse_actuaciones(html)

    def parse_intervinientes(self, html_content: str) -> IntervinientesList:
        # Extract from CDATA if this is an AJAX response
        cdata = _extract_main_cdata(html_content)
        if cdata:
            html_content = cdata

        soup = _bs(html_content)
        partes = self._parse_participants_table(soup)
        fiscales = self._parse_fiscales_table(soup)

        return IntervinientesList(partes=partes, fiscales=fiscales)

    def _parse_participants_table(self, soup: BeautifulSoup) -> list[Interviniente]:
        partes: list[Interviniente] = []
        party_data: dict[int, dict] = {}

        # Main party rows: <tbody id="expediente:participantsTable:N:tb">
        for tbody in soup.find_all("tbody", id=re.compile(r'participantsTable:\d+:tb$')):
            idx_match = re.search(r'participantsTable:(\d+):tb', tbody.get("id", ""))
            if not idx_match:
                continue
            idx = int(idx_match.group(1))

            strong_spans = tbody.find_all("span", class_="font-strong")
            tipo = strong_spans[0].get_text(strip=True) if len(strong_spans) >= 1 else ""
            nombre = strong_spans[1].get_text(strip=True) if len(strong_spans) >= 2 else ""

            party_data[idx] = {"tipo": tipo, "nombre": nombre, "letrados": []}

        # Letrado subtables: <tbody id="expediente:participantsTable:N:j_idt...:c">
        for tbody in soup.find_all("tbody", id=re.compile(r'participantsTable:\d+:j_idt\d+:c')):
            idx_match = re.search(r'participantsTable:(\d+):', tbody.get("id", ""))
            if not idx_match:
                continue
            idx = int(idx_match.group(1))
            if idx not in party_data:
                continue

            for tr in tbody.find_all("tr", id=re.compile(r':\d+:b$')):
                cells = tr.find_all("td", class_=re.compile(r'rf-cst-c'))
                if len(cells) >= 4:
                    party_data[idx]["letrados"].append(Letrado(
                        tipo=cells[0].get_text(strip=True),
                        nombre=cells[1].get_text(strip=True),
                        tomo_folio=cells[2].get_text(strip=True) or None,
                        iej=cells[3].get_text(strip=True) or None,
                    ))

        for idx in sorted(party_data.keys()):
            data = party_data[idx]
            partes.append(Interviniente(
                tipo=data["tipo"],
                nombre=data["nombre"],
                letrados=data["letrados"],
            ))

        return partes

    def _parse_fiscales_table(self, soup: BeautifulSoup) -> list[Fiscal]:
        fiscales: list[Fiscal] = []

        table = soup.find("table", id="expediente:fiscalesTable")
        if not table:
            return fiscales

        for tr in table.find_all("tr", id=re.compile(r'fiscalesTable:\d+')):
            cells = tr.find_all("td", class_="rf-dt-c")
            if len(cells) >= 3:
                fiscales.append(Fiscal(
                    fiscalia=cells[0].get_text(strip=True),
                    fiscal=cells[1].get_text(strip=True),
                    iej=cells[2].get_text(strip=True) or None,
                ))

        return fiscales


# =============================================================================
# RELACIONADOS PARSER
# =============================================================================


class RelacionadosParser:
    """Parser for extracting data from consultaListaRelacionados.seam page."""

    def __init__(self):
        self._favoritos_parser = FavoritosParser()

    def parse(self, html_content: str) -> RelacionadosPage:
        soup = _bs(html_content)
        view_state = _extract_view_state(soup)

        profiles = self._extract_profiles(soup)
        is_empty = "No se han encontrado expedientes" in html_content

        # Always try to parse expedientes — PJN may show both profiles
        # and the expedientes table on the same page after selection.
        expedientes = self._favoritos_parser.parse(html_content)
        has_expedientes = len(expedientes.expedientes) > 0

        if profiles and not has_expedientes:
            return RelacionadosPage(
                profiles=profiles,
                expedientes=ExpedienteList(expedientes=[], total_count=0),
                view_state=view_state,
                selected_profile=None,
                is_empty=False,
            )

        selected_profile = self._detect_selected_profile(html_content)

        return RelacionadosPage(
            profiles=profiles,
            expedientes=expedientes,
            view_state=view_state,
            selected_profile=selected_profile,
            is_empty=is_empty if not has_expedientes else False,
        )

    def _extract_profiles(self, soup: BeautifulSoup) -> list[RelacionadosProfile]:
        profiles: list[RelacionadosProfile] = []

        for btn in soup.find_all(
            "input",
            id=re.compile(r'dataTablePerfiles:\d+:btnConsultaExpedientesSAU'),
        ):
            idx_match = re.search(r'dataTablePerfiles:(\d+):', btn.get("id", ""))
            if idx_match:
                index = int(idx_match.group(1))
                nombre = btn.get("value", "").strip()
                profiles.append(RelacionadosProfile(nombre=nombre, index=index))

        return profiles

    def _detect_selected_profile(self, html_content: str) -> Optional[str]:
        upper = html_content.upper()
        if "AUTORIZADO" in upper:
            return "AUTORIZADO NE"
        if "LETRADO" in upper:
            return "LETRADO"
        return None

    def extract_form_ids(self, html_content: str) -> dict:
        soup = _bs(html_content)

        btn = soup.find(
            "input",
            id=re.compile(r'dataTablePerfiles'),
        )
        if btn:
            match = re.search(r'^([^:]+:[^:]+):dataTablePerfiles', btn.get("id", ""))
            if match:
                return {"form_id": match.group(1)}

        return {"form_id": "j_idt76:j_idt78"}

    def extract_page_ids(self, html_content: str) -> dict[int, str]:
        soup = _bs(html_content)
        page_ids: dict[int, str] = {}

        pagination_div = soup.find("div", id=re.compile(r':divPagesAct$'))
        if not pagination_div:
            return page_ids

        for a in pagination_div.find_all("a", id=True):
            a_id = a.get("id", "")
            if not re.search(r':\d+:j_idt\d+$', a_id):
                continue
            span = a.find("span")
            if span and span.get_text(strip=True).isdigit():
                page_num = int(span.get_text(strip=True))
                page_ids[page_num] = a_id

        return page_ids

    def extract_form_id_from_table(self, html_content: str) -> str:
        soup = _bs(html_content)
        form = soup.find(True, id=re.compile(r'tablaConsultaForm'))
        if form:
            return form.get("id", "tablaConsultaLista:tablaConsultaForm")
        return "tablaConsultaLista:tablaConsultaForm"

    def extract_next_page_id(self, html_content: str) -> Optional[str]:
        """
        Extract the "Siguiente" (Next) pagination link element ID.

        More reliable than numbered page links because "Siguiente" is always
        present when there are more pages, whereas numbered links may only
        show a subset of available pages.
        """
        soup = _bs(html_content)

        siguiente_span = soup.find("span", title="Siguiente")
        if siguiente_span:
            parent_a = siguiente_span.find_parent("a")
            if parent_a and parent_a.get("id"):
                return parent_a.get("id")

        return None

    def extract_view_state_from_ajax(self, xml_content: str) -> Optional[str]:
        return _extract_view_state_from_ajax(xml_content)

    def extract_html_from_ajax(self, xml_content: str) -> Optional[str]:
        return _extract_main_cdata(xml_content)

    def parse_from_ajax(self, xml_content: str) -> ExpedienteList:
        html = self.extract_html_from_ajax(xml_content)
        if not html:
            return ExpedienteList(expedientes=[], total_count=0)
        return self._favoritos_parser.parse(html)


# =============================================================================
# SCW SEARCH RESULTS PARSER
# =============================================================================


class SCWSearchResultsParser:
    """
    Parser for SCW public search result pages.

    Handles both result formats:
    - 5-column (consultaParte.seam): Expediente | Dependencia | Caratula | Situacion | Ult.Act. | [action]
    - 7-column (listaSeleccionExpediente.seam): Expediente | Tomo | Letra | Dependencia | Caratula | Situacion | Ult.Act. | [action]

    Also extracts navigation info (form_id + button_id) for clicking
    on a specific result to view its detail page.
    """

    def parse_results(self, html: str, url: str = "") -> list[SCWResult]:
        """Parse search results from both 5-col and 7-col formats."""
        soup = _bs(html)

        # Find the table containing results — has <td class="column"> cells
        table = None
        for t in soup.find_all("table"):
            if t.find("td", class_="column"):
                table = t
                break

        if not table:
            return []

        tbody = table.find("tbody")
        if not tbody:
            return []

        is_7col = "listaSeleccionExpediente" in url
        results: list[SCWResult] = []

        for row in tbody.find_all("tr"):
            columns = row.find_all("td", class_="column")

            if is_7col and len(columns) >= 5:
                # 7-col: columns are Expediente | Tomo | Letra | Dependencia | Caratula
                # Situacion and Ult.Act. are in text-center cells
                text_center_cols = row.find_all("td", class_=re.compile(r'^text-center'))
                results.append(SCWResult(
                    numero=columns[0].get_text(strip=True),
                    tomo=columns[1].get_text(strip=True),
                    letra=columns[2].get_text(strip=True),
                    dependencia=columns[3].get_text(strip=True),
                    caratula=columns[4].get_text(strip=True),
                    situacion=text_center_cols[0].get_text(strip=True) if text_center_cols else "",
                    ultima_actualizacion=text_center_cols[1].get_text(strip=True) if len(text_center_cols) > 1 else "",
                ))
            elif len(columns) >= 5:
                # 5-col: Expediente | Dependencia | Caratula | Situacion | Ult.Act.
                results.append(SCWResult(
                    numero=columns[0].get_text(strip=True),
                    dependencia=columns[1].get_text(strip=True),
                    caratula=columns[2].get_text(strip=True),
                    situacion=columns[3].get_text(strip=True),
                    ultima_actualizacion=columns[4].get_text(strip=True),
                ))

        return results

    def extract_result_navigation(
        self, html: str, row_index: int
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Extract form_id and button_id for navigating to a specific result's detail.

        Searches for JSF component IDs containing ``dataTable:{row_index}:``
        in onclick handlers and element id attributes.

        Returns:
            Tuple of (form_id, button_id), or (None, None) if not found.
        """
        soup = _bs(html)
        target = f"dataTable:{row_index}:"
        escaped_target = re.escape(target)

        # JSF component ID pattern: word chars and colons containing the target
        component_pattern = re.compile(r'([\w:]+' + escaped_target + r'[\w]+)')

        # Strategy 1: onclick handlers containing the target
        for tag in soup.find_all(True, onclick=True):
            onclick = tag.get("onclick", "")
            if target not in onclick:
                continue
            match = component_pattern.search(onclick)
            if match:
                button_id = match.group(1)
                form_id = self._find_form_id(soup, button_id)
                return form_id, button_id

        # Strategy 2: element id attributes containing the target
        for tag in soup.find_all(True, id=re.compile(escaped_target)):
            tag_id = tag.get("id", "")
            # Prefer clickable elements
            if tag.name in ("a", "input", "button"):
                form_id = self._find_form_id(soup, tag_id)
                return form_id, tag_id

        return None, None

    @staticmethod
    def _find_form_id(soup: BeautifulSoup, button_id: str) -> Optional[str]:
        """Derive the form_id from a button_id or the page's form element."""
        # Try to derive from button_id prefix (everything before :dataTable:)
        if ":dataTable:" in button_id:
            # e.g. "formConsultaParte:j_idt123:dataTable:0:link" → try "formConsultaParte:j_idt123"
            # then try "formConsultaParte"
            prefix = button_id.split(":dataTable:")[0]
            # Check if this prefix matches a form id exactly
            form = soup.find("form", id=prefix)
            if form:
                return prefix
            # Try just the first segment (before the first colon)
            first_segment = prefix.split(":")[0]
            form = soup.find("form", id=first_segment)
            if form:
                return first_segment

        # Fall back to first form on page
        form = soup.find("form")
        return form.get("id") if form else None
