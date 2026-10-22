"""Parser for extracting set ID from POSLoguin response (Fuero de Familia)."""

from typing import Optional

from .base import BaseParser


class SetIdParser(BaseParser[Optional[str]]):
    """
    Extracts the authorized set ID from the POSLoguin response page.

    In Fuero de Familia flow, after POSLoguin, the page contains a dropdown
    with authorized sets. We look for the option containing
    "Lista de Causas con AUTORIZACION" to get the set ID.

    Example HTML:
        <select name="Set">
            <option value="1662249">Lista de Causas con AUTORIZACION para...</option>
        </select>
    """

    SET_MARKER = "Lista de Causas con AUTORIZACION"

    def parse(self, html_content: str) -> Optional[str]:
        """
        Parse the set ID from the POSLoguin response.

        Args:
            html_content: HTML content from POSLoguin response

        Returns:
            Set ID string if found, None otherwise
        """
        soup = self._make_soup(html_content)

        # Look for option elements containing the marker text
        for option in soup.find_all("option"):
            text = option.get_text()
            if self.SET_MARKER in text:
                value = option.get("value", "").strip()
                # Validate it's a numeric ID
                if value and value.isdigit():
                    return value

        return None

    def has_familia_access(self, html_content: str) -> bool:
        """
        Check if the user has access to Fuero de Familia causas.

        Args:
            html_content: HTML content from POSLoguin response

        Returns:
            True if the user has authorized familia causas, False otherwise
        """
        return self.parse(html_content) is not None
