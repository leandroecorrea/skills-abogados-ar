"""Parser for MEV file orders page (procesales.asp)."""

import re
from datetime import datetime
from typing import Optional
from bs4 import Tag

from .base import BaseParser
from ..models import OrderSummary, CourtFile, FullCourtFile


class FileOrdersPageParser(BaseParser[list[OrderSummary]]):
    """
    Parser for the file orders page (procesales.asp).

    Extracts order summaries from the "Pasos Procesales" table.
    """

    # Pattern to extract proveido.asp parameters
    PROVEIDO_PATTERN = re.compile(
        r"pidJuzgado=([^&]+)&sCodi=([^&]+)&nPosi=([^&]+)&sFile=([^&]+)"
    )

    # Date patterns
    DATE_TIME_PATTERN = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}:\d{2})")
    DATE_ONLY_PATTERN = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")

    def parse(self, html_content: str) -> list[OrderSummary]:
        """
        Parse the file orders page to extract order summaries.

        Args:
            html_content: HTML response from procesales.asp

        Returns:
            List of OrderSummary objects
        """
        soup = self._make_soup(html_content)
        orders: list[OrderSummary] = []

        # Check for "sin pasos" indicator
        if self._indicates_no_orders(soup):
            return orders

        # Find the orders table (the one with Fecha/Fojas/Firmado/Descripcion headers)
        orders_table = self._find_orders_table(soup)
        if orders_table is None:
            return orders

        # Find all order rows (rows with proveido.asp links)
        for row in orders_table.find_all("tr"):
            link = row.find("a", href=lambda h: h and "proveido.asp" in h)
            if link:
                order = self._parse_order_row(row, link)
                if order:
                    orders.append(order)

        return orders

    def parse_full_file(
        self, html_content: str, case_id: str, court_id: str
    ) -> FullCourtFile:
        """
        Parse full file information including file details, orders, and court info.

        Args:
            html_content: HTML response from procesales.asp
            case_id: The case ID (nidCausa)
            court_id: The court ID (pidJuzgado)

        Returns:
            FullCourtFile with all extracted information
        """
        soup = self._make_soup(html_content)
        orders = self.parse(html_content)

        # Extract file info from the page
        file_info = self._extract_file_info(soup, case_id, court_id)

        # Extract court name and district name from header
        court_name = self._extract_court_name(soup)
        district_name = self._extract_district_name(soup)

        return FullCourtFile(
            file=file_info,
            orders=orders,
            court_name=court_name,
            district_name=district_name,
        )

    def parse_with_file_info(
        self, html_content: str, case_id: str, court_id: str
    ) -> tuple[Optional[CourtFile], list[OrderSummary]]:
        """
        Parse both file info and orders from the page.

        Args:
            html_content: HTML response from procesales.asp
            case_id: The case ID (nidCausa)
            court_id: The court ID (pidJuzgado)

        Returns:
            Tuple of (CourtFile, list[OrderSummary])
        """
        soup = self._make_soup(html_content)
        orders = self.parse(html_content)

        # Try to extract file info from the page header
        file_info = self._extract_file_info(soup, case_id, court_id)

        return file_info, orders

    def _find_orders_table(self, soup) -> Optional[Tag]:
        """Find the table containing the orders."""
        # Look for table with header row containing "Fecha", "Fojas", "Firmado", "Descripcion"
        for table in soup.find_all("table"):
            header_row = table.find("tr")
            if header_row:
                header_text = header_row.get_text().lower()
                if "fecha" in header_text and "descripcion" in header_text:
                    return table

        # Fallback: look for "Pasos Procesales" header
        for strong in soup.find_all("strong"):
            if "Pasos Procesales" in strong.get_text():
                # Find the next table after this header
                parent = strong.find_parent("table")
                if parent:
                    # Look for sibling table with proveido links
                    next_table = parent.find_next_sibling("table")
                    if next_table and next_table.find("a", href=lambda h: h and "proveido.asp" in h):
                        return next_table
                    # Or the parent table itself
                    return parent

        # Last fallback: look for table with proveido links
        for table in soup.find_all("table"):
            if table.find("a", href=lambda h: h and "proveido.asp" in h):
                return table

        return None

    def _indicates_no_orders(self, soup) -> bool:
        """Check if the page indicates no orders exist."""
        text = soup.get_text().lower()
        no_orders_phrases = [
            "sin pasos",
            "sin pasos procesales",
            "no hay pasos",
        ]
        return any(phrase in text for phrase in no_orders_phrases)

    def _parse_order_row(self, row: Tag, link: Tag) -> Optional[OrderSummary]:
        """
        Parse a single order from its table row.

        Args:
            row: The <tr> element containing the order
            link: The <a> element with href to proveido.asp

        Returns:
            OrderSummary or None if parsing fails
        """
        href = link.get("href", "")
        match = self.PROVEIDO_PATTERN.search(href)
        if not match:
            return None

        court_id = match.group(1)
        order_code = match.group(2)
        position = match.group(3)
        file_type = match.group(4)

        # Get order title from link text
        title = self._clean_text(link.get_text())

        # Get all table cells
        tds = row.find_all("td")

        # Parse datetime from first column
        order_date = datetime.min
        fojas = ""
        is_signed = False

        if len(tds) >= 1:
            # Column 1: Date (may include time)
            date_text = self._clean_text(tds[0].get_text())
            order_date = self._parse_datetime(date_text) or datetime.min

        if len(tds) >= 2:
            # Column 2: Fojas (page numbers)
            fojas = self._clean_text(tds[1].get_text())

        if len(tds) >= 3:
            # Column 3: Firmado (signature indicator)
            # Check for presence of signature image
            is_signed = tds[2].find("img") is not None

        return OrderSummary(
            date=order_date,
            title=title,
            order_code=order_code,
            position=position,
            file_type=file_type,
            court_id=court_id,
            fojas=fojas,
            is_signed=is_signed,
        )

    def _parse_datetime(self, text: str) -> Optional[datetime]:
        """
        Parse datetime from text, handling both date-only and date+time formats.

        Args:
            text: Text containing date/datetime

        Returns:
            datetime object or None if parsing fails
        """
        if not text:
            return None

        # Try date + time format first (DD/MM/YYYY HH:MM:SS)
        match = self.DATE_TIME_PATTERN.search(text)
        if match:
            try:
                date_str = match.group(1)
                time_str = match.group(2)
                return datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M:%S")
            except ValueError:
                pass

        # Try date-only format (DD/MM/YYYY)
        match = self.DATE_ONLY_PATTERN.search(text)
        if match:
            try:
                return datetime.strptime(match.group(1), "%d/%m/%Y")
            except ValueError:
                pass

        # Fallback to base class method
        return self._parse_date(text)

    def _extract_court_name(self, soup) -> str:
        """Extract court name from page header."""
        # Look for <p class="whitecenter"> in fondoazul cell
        for p in soup.find_all("p", class_="whitecenter"):
            text = self._clean_text(p.get_text())
            if text and "Juzgado" in text:
                return text
        return ""

    def _extract_district_name(self, soup) -> str:
        """Extract district name from page header."""
        # Look for <p class="whiteright"> in fondoazul cell
        for p in soup.find_all("p", class_="whiteright"):
            parent_td = p.find_parent("td")
            if parent_td and "fondoazul" in parent_td.get("class", []):
                text = self._clean_text(p.get_text())
                if text:
                    return text
        return ""

    def _extract_file_info(
        self, soup, case_id: str, court_id: str
    ) -> Optional[CourtFile]:
        """
        Extract file information from the page.

        Args:
            soup: BeautifulSoup object
            case_id: The case ID
            court_id: The court ID

        Returns:
            CourtFile with extracted info, or None if the file was not found
        """
        case_caption = ""
        initial_date = None
        reception_number = ""
        file_number = ""
        status = ""

        # Find "Datos del Expediente" section
        fondoceleste_cells = soup.find_all("td", class_="fondoceleste")

        # If no fondoceleste cells found, the file doesn't exist
        if not fondoceleste_cells:
            return None

        for td in fondoceleste_cells:
            text = td.get_text()

            # Extract case caption (Caratula/Carátula)
            if "Caratula:" in text or "Carátula:" in text or "Car\xe1tula:" in text:
                # Handle both ASCII and accented versions
                for sep in ["Carátula:", "Car\xe1tula:", "Caratula:"]:
                    if sep in text:
                        parts = text.split(sep)
                        if len(parts) > 1:
                            case_caption = self._clean_text(parts[1])
                            break

            # Extract initial date (Fecha inicio)
            if "Fecha inicio:" in text:
                parts = text.split("Fecha inicio:")
                if len(parts) > 1:
                    date_text = self._clean_text(parts[1])
                    initial_date = self._parse_date(date_text)

            # Extract reception number (Nro de Receptoria)
            if "Receptoria:" in text:
                parts = text.split("Receptoria:")
                if len(parts) > 1:
                    reception_number = self._clean_text(parts[1])

            # Extract file number (Nro de Expediente / Nº de Expediente / Expediente)
            if "Expediente:" in text:
                parts = text.split("Expediente:")
                if len(parts) > 1:
                    file_number = self._clean_text(parts[1])

            # Extract status (Estado)
            if "Estado:" in text:
                parts = text.split("Estado:")
                if len(parts) > 1:
                    status = self._clean_text(parts[1])

        # If we found the fondoceleste section but no case caption, the file doesn't exist
        if not case_caption:
            return None

        return CourtFile(
            id=case_id,
            court_id=court_id,
            case_caption=case_caption,
            status=status,
            reception_number=reception_number,
            file_number=file_number,
            initial_date=initial_date,
        )

    def get_last_order(self, html_content: str) -> Optional[OrderSummary]:
        """
        Get the most recent order from the page.

        Args:
            html_content: HTML response from procesales.asp

        Returns:
            Most recent OrderSummary or None
        """
        orders = self.parse(html_content)
        if not orders:
            return None
        return max(orders, key=lambda o: o.date)
