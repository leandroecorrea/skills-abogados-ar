"""HTML parsers for MEV pages.

This package contains specialized parsers for each MEV page type:
- LoginPageParser: Extracts user info from login response
- SearchResultPageParser: Extracts court files from search results
- FileOrdersPageParser: Extracts order summaries from procesales.asp
- OrderPageParser: Extracts order text from proveido.asp
- SetIdParser: Extracts set ID from POSLoguin response (Familia)
- JuzgadosDropdownParser: Extracts juzgados from results page dropdown
"""

from .login import LoginPageParser
from .search_results import SearchResultPageParser
from .file_orders import FileOrdersPageParser
from .order import OrderPageParser
from .set_id import SetIdParser
from .juzgados_dropdown import JuzgadosDropdownParser, JuzgadoInfo

__all__ = [
    "LoginPageParser",
    "SearchResultPageParser",
    "FileOrdersPageParser",
    "OrderPageParser",
    "SetIdParser",
    "JuzgadosDropdownParser",
    "JuzgadoInfo",
]
