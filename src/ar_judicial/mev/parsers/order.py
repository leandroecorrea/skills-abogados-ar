"""Parser for MEV order page (proveido.asp)."""

import re
from datetime import datetime
from typing import Optional

from .base import BaseParser
from ..models import FileOrder, Attachment


class OrderPageParser(BaseParser[Optional[FileOrder]]):
    """
    Parser for the order text page (proveido.asp).

    Extracts the full text content of a court order.
    """

    # Pattern to extract date and title from header
    DATE_TITLE_PATTERN = re.compile(
        r"(\d{1,2}/\d{1,2}/\d{4})\s*(\d{1,2}:\d{2}:\d{2})?\s*-\s*(.+)"
    )

    # Pattern for datetime with time
    DATETIME_PATTERN = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}:\d{2})")

    def parse(
        self,
        html_content: str,
        court_id: str = "",
        case_id: str = "",
        order_code: str = "",
        position: str = "",
    ) -> Optional[FileOrder]:
        """
        Parse the order page to extract order details.

        Args:
            html_content: HTML response from proveido.asp
            court_id: Court ID (pidJuzgado)
            case_id: Case ID (nidCausa)
            order_code: Order code (sCodi)
            position: Position (nPosi)

        Returns:
            FileOrder with full text or None if parsing fails
        """
        soup = self._make_soup(html_content)

        # Extract order date and title from header
        order_date, title = self._extract_date_and_title(soup)

        # Extract order text (clean, without markers)
        text = self._extract_order_text(soup)

        # Extract references metadata
        signed_by = self._extract_reference_field(soup, "Firmado por")
        observation = self._extract_reference_field(soup, "Observacion")
        submission_number = self._extract_reference_field(soup, "Nro. Presentacion Electronica")
        submission_date_str = self._extract_reference_field(soup, "Fecha del Escrito")
        submission_date = self._parse_datetime(submission_date_str) if submission_date_str else None

        # Extract attachments
        attachments = self._extract_attachments(soup)

        if not text and not title:
            return None

        return FileOrder(
            date=order_date or datetime.min,
            title=title,
            text=text,
            order_code=order_code,
            position=position,
            court_id=court_id,
            case_id=case_id,
            signed_by=signed_by,
            observation=observation,
            submission_number=submission_number,
            submission_date=submission_date,
            attachments=attachments,
        )

    def _extract_date_and_title(self, soup) -> tuple[Optional[datetime], str]:
        """
        Extract the order date and title from the header.

        Looks for pattern like: "10/04/2025 9:33:31 - DEMANDA - SE PRESENTA"
        """
        # Look for the header cell with date and title
        for td in soup.find_all("td", class_="fondoclaro"):
            p = td.find("p", class_="center")
            if p:
                b = p.find("b")
                if b:
                    text = self._clean_text(b.get_text())
                    match = self.DATE_TITLE_PATTERN.search(text)
                    if match:
                        date_str = match.group(1)
                        time_str = match.group(2) or "00:00:00"
                        title = match.group(3).strip()

                        try:
                            order_date = datetime.strptime(
                                f"{date_str} {time_str}", "%d/%m/%Y %H:%M:%S"
                            )
                            return order_date, title
                        except ValueError:
                            return None, title

        # Fallback: try to find any date/title pattern
        return self._extract_order_date_fallback(soup), self._extract_order_title_fallback(soup)

    def _extract_order_date_fallback(self, soup) -> Optional[datetime]:
        """Fallback method to extract order date."""
        date_pattern = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")
        for p in soup.find_all("p")[:10]:
            text = p.get_text()
            match = date_pattern.search(text)
            if match:
                return self._parse_date(match.group(1))
        return None

    def _extract_order_title_fallback(self, soup) -> str:
        """Fallback method to extract order title."""
        title_patterns = [
            "SENTENCIA", "AUTO", "DESPACHO", "PROVIDENCIA",
            "INTIMACION", "RESOLUCION", "DEMANDA", "PASE"
        ]
        for elem in soup.find_all(["h1", "h2", "h3", "strong", "b"]):
            text = self._clean_text(elem.get_text()).upper()
            for pattern in title_patterns:
                if pattern in text:
                    return text
        return "DESPACHO"

    def _extract_order_text(self, soup) -> str:
        """
        Extract the main order text content.

        Looks for the div with id="contenidoTxt" and extracts text
        between the "Para copiar y pegar" markers, excluding those markers.
        """
        # Find the content div
        content_div = soup.find("div", id="contenidoTxt")
        if not content_div:
            # Try other containers
            content_div = soup.find("div", class_=lambda c: c and "contenido" in str(c).lower())

        if not content_div:
            return ""

        # Get the HTML content
        html_content = str(content_div)

        # Remove the "Para copiar y pegar" marker lines
        # These are in <span class="EstiloLineaCorte">
        for span in content_div.find_all("span", class_="EstiloLineaCorte"):
            span.decompose()

        # Also remove signature blocks at the end
        for div in content_div.find_all("div", class_="EstiloFirma"):
            div.decompose()

        # Get text from remaining content
        text_parts = []
        for elem in content_div.find_all(["p", "li"]):
            text = self._clean_text(elem.get_text())
            if text:
                text_parts.append(text)

        return "\n\n".join(text_parts)

    def _extract_reference_field(self, soup, field_name: str) -> str:
        """
        Extract a field from the References section.

        Args:
            soup: BeautifulSoup object
            field_name: The field label to look for (e.g., "Firmado por")

        Returns:
            Field value or empty string
        """
        for td in soup.find_all("td", class_="fondoceleste"):
            strong = td.find("strong")
            if strong:
                label = self._clean_text(strong.get_text())
                if label == field_name:
                    # Get the text after the label
                    full_text = self._clean_text(td.get_text())
                    # Remove the label part
                    value = full_text.replace(label, "", 1).strip()
                    return value
        return ""

    def _extract_attachments(self, soup) -> list[Attachment]:
        """
        Extract PDF attachments from the References section.

        Attachments are rows with a PDF filename and "VER ADJUNTO" link.
        """
        attachments = []
        seen_urls = set()  # Avoid duplicates

        for td in soup.find_all("td", class_="fondoceleste"):
            strong = td.find("strong")
            link = td.find("a")

            if strong and link:
                name = self._clean_text(strong.get_text())
                # Only capture actual file attachments (PDFs, etc.)
                if name.endswith(".pdf") or name.endswith(".doc") or name.endswith(".docx"):
                    url = link.get("href", "")
                    # Ensure it's a document URL, not an internal link
                    if url and "docs.scba.gov.ar" in url and url not in seen_urls:
                        seen_urls.add(url)
                        attachments.append(Attachment(name=name, url=url))

        return attachments

    def _parse_datetime(self, text: str) -> Optional[datetime]:
        """Parse datetime from text."""
        if not text:
            return None

        match = self.DATETIME_PATTERN.search(text)
        if match:
            try:
                date_str = match.group(1)
                time_str = match.group(2)
                return datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M:%S")
            except ValueError:
                pass

        # Try date only
        return self._parse_date(text)

    def get_raw_text(self, html_content: str) -> str:
        """
        Get all text content from the page.

        Useful for debugging or when structured parsing fails.

        Args:
            html_content: HTML response

        Returns:
            Raw text content
        """
        soup = self._make_soup(html_content)

        # Remove script and style elements
        for elem in soup(["script", "style", "head"]):
            elem.decompose()

        return self._clean_text(soup.get_text(separator="\n"))
