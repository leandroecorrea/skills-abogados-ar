"""Parser for MEV search results page (MuestraCausas.asp)."""

import re
from typing import Optional
from bs4 import Tag

from .base import BaseParser
from ..models import CourtFile


class SearchResultPageParser(BaseParser[list[CourtFile]]):
    """
    Parser for the search results page (MuestraCausas.asp).

    Extracts court files from the results table. The table structure has paired rows:
    - Row 1 (caption row): Contains the case caption in a link
    - Row 2 (data row): Contains status, reception_number, file_number, initial_date, last_update
    """

    # Pattern to extract nidCausa and pidJuzgado from href
    PROCESALES_PATTERN = re.compile(r"nidCausa=(\d+)&pidJuzgado=(\w+)")
    # Pattern to extract page number from pagination links
    PAGINA_PATTERN = re.compile(r"pagina=(\d+)")

    def parse(self, html_content: str) -> list[CourtFile]:
        """
        Parse search results HTML to extract court files.

        Args:
            html_content: HTML response from search

        Returns:
            List of CourtFile objects
        """
        soup = self._make_soup(html_content)
        court_files: list[CourtFile] = []

        if not self._validate_document(soup):
            return court_files

        tbody = self._find_results_table(soup)
        if tbody is None:
            return court_files

        rows = tbody.find_all("tr", recursive=False)
        if not rows:
            rows = tbody.find_all("tr")

        # Process rows in pairs
        i = 0
        while i < len(rows) - 1:
            try:
                file = self._parse_file_pair(rows[i], rows[i + 1])
                if file:
                    court_files.append(file)
            except Exception:
                pass  # Skip malformed rows
            i += 2

        return court_files

    def _find_results_table(self, soup) -> Optional[Tag]:
        """Find the tbody containing search results."""
        for tbody in soup.find_all("tbody"):
            if tbody.find("div", class_="AnchoFijoCaratula"):
                return tbody
        return None

    def _validate_document(self, soup) -> bool:
        """Check if the HTML contains valid search results."""
        results_table = self._find_results_table(soup)
        if results_table is None:
            return False

        rows = results_table.find_all("tr")
        if len(rows) % 2 != 0:
            return False

        return True

    def _parse_file_pair(self, caption_row: Tag, data_row: Tag) -> Optional[CourtFile]:
        """
        Parse a pair of rows into a CourtFile.

        Args:
            caption_row: First row containing case caption
            data_row: Second row containing metadata

        Returns:
            CourtFile object or None if parsing fails
        """
        # =====================================================================
        # ROW 1: Extract case ID, court ID, and caption
        # =====================================================================
        case_id = ""
        court_id = ""
        case_caption = ""

        # Try to get from link href first
        caption_link = caption_row.select_one("td div p a")
        if caption_link:
            case_caption = self._clean_text(caption_link.get_text())
            href = caption_link.get("href", "")
            match = self.PROCESALES_PATTERN.search(href)
            if match:
                case_id = match.group(1)
                court_id = match.group(2)

        # Fallback: get court_id from hidden input
        if not court_id:
            hidden_input = caption_row.find("input", {"type": "hidden"})
            if hidden_input:
                court_id = hidden_input.get("value", "").strip()

        # Fallback: get case_id from checkbox
        if not case_id:
            checkbox = caption_row.find("input", {"type": "checkbox"})
            if checkbox:
                case_id = checkbox.get("value", "")

        # =====================================================================
        # ROW 2: Extract data columns
        # Column 1: Status (Estado)
        # Column 2: Reception Number (Nro de Receptoria)
        # Column 3: File Number (Nro de Expediente)
        # Column 4: Initial Date (Fecha de Inicio)
        # Column 5: Last Update (Ultimo despacho) - in link
        # =====================================================================
        paragraphs = data_row.find_all("p")

        # Column 1: Status
        status = ""
        if len(paragraphs) >= 1:
            status = self._clean_text(paragraphs[0].get_text())
            status = status if status else "SIN DATOS"

        # Column 2: Reception Number (Nro de Receptoria)
        reception_number = ""
        if len(paragraphs) >= 2:
            reception_number = self._clean_text(paragraphs[1].get_text())

        # Column 3: File Number (Nro de Expediente)
        file_number = ""
        if len(paragraphs) >= 3:
            file_number = self._clean_text(paragraphs[2].get_text())

        # Column 4: Initial Date (Fecha de Inicio)
        initial_date = None
        if len(paragraphs) >= 4:
            initial_date = self._parse_date(paragraphs[3].get_text().strip())

        # Column 5: Last Update + Order Title (Ultimo despacho)
        last_update = None
        last_order_title = ""
        last_update_link = data_row.find("a")
        if last_update_link:
            link_text = self._clean_text(last_update_link.get_text())
            if link_text and "-" in link_text:
                parts = link_text.split("-", 1)
                if len(parts) == 2:
                    last_update = self._parse_date(parts[0].strip())
                    last_order_title = parts[1].strip()

        return CourtFile(
            id=case_id,
            court_id=court_id,
            case_caption=case_caption,
            status=status,
            reception_number=reception_number,
            file_number=file_number,
            initial_date=initial_date,
            last_update=last_update,
            last_order_title=last_order_title,
        )

    def get_last_page(self, html_content: str) -> int:
        """
        Extract the last page number from pagination links.

        Looks for the "Ultima" link which contains the last page number:
        <a href="MuestraCausas.asp?radio=xCa&pagina=6&pOrden=xCa&pOrdenAD=Asc&NroColumna=0">Ultima</a>

        Args:
            html_content: HTML response from search

        Returns:
            Last page number (1 if no pagination)
        """
        soup = self._make_soup(html_content)
        ultima_link = soup.find("a", string=re.compile(r"[UÚuú]ltima"))
        if ultima_link:
            href = ultima_link.get("href", "")
            match = self.PAGINA_PATTERN.search(href)
            if match:
                return int(match.group(1))
        return 1

    def get_total_count(self, html_content: str) -> int:
        """
        Extract the total number of results from the page.

        Args:
            html_content: HTML response from search

        Returns:
            Total count of results
        """
        soup = self._make_soup(html_content)

        # Look for "Total Expedientes : N"
        total_pattern = re.compile(r"Total\s+Expedientes\s*:\s*(\d+)")
        text = soup.get_text()
        match = total_pattern.search(text)
        if match:
            return int(match.group(1))

        return 0
