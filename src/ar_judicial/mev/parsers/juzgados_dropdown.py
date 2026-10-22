"""Parser for extracting juzgados from results page dropdown."""

from dataclasses import dataclass
from typing import Optional

from .base import BaseParser


@dataclass
class JuzgadoInfo:
    """Information about a juzgado from the dropdown."""

    id: str  # The value attribute (e.g., "FAM1234")
    name: str  # The display text (e.g., "Juzgado de Familia Nro. 1")


class JuzgadosDropdownParser(BaseParser[list[JuzgadoInfo]]):
    """
    Extracts juzgados from the results page dropdown.

    The results page contains a <select id="JuzgadoElegido"> with all
    juzgados available for the current search context.

    Example HTML:
        <select id="JuzgadoElegido" name="JuzgadoElegido">
            <option value="">Todos</option>
            <option value="FAM1234">Juzgado de Familia Nro. 1</option>
            <option value="FAM5678">Juzgado de Familia Nro. 2</option>
        </select>
    """

    DROPDOWN_ID = "JuzgadoElegido"

    def parse(self, html_content: str) -> list[JuzgadoInfo]:
        """
        Parse juzgados from the results page dropdown.

        Args:
            html_content: HTML content from results page

        Returns:
            List of JuzgadoInfo objects (excludes empty "Todos" option)
        """
        soup = self._make_soup(html_content)
        juzgados: list[JuzgadoInfo] = []

        # Find the select element by ID
        select = soup.find("select", {"id": self.DROPDOWN_ID})
        if not select:
            # Try by name as fallback
            select = soup.find("select", {"name": self.DROPDOWN_ID})

        if not select:
            return juzgados

        # Extract all options
        for option in select.find_all("option"):
            value = option.get("value", "").strip()
            name = self._clean_text(option.get_text())

            # Skip empty values (usually "Todos" or placeholder)
            if value:
                juzgados.append(JuzgadoInfo(id=value, name=name))

        return juzgados

    def get_juzgado_by_id(
        self, html_content: str, juzgado_id: str
    ) -> Optional[JuzgadoInfo]:
        """
        Get a specific juzgado by ID from the dropdown.

        Args:
            html_content: HTML content from results page
            juzgado_id: The juzgado ID to find

        Returns:
            JuzgadoInfo if found, None otherwise
        """
        juzgados = self.parse(html_content)
        for juzgado in juzgados:
            if juzgado.id == juzgado_id:
                return juzgado
        return None
