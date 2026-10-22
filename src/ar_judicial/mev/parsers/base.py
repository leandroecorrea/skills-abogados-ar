"""Base parser class with common utilities."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, TypeVar, Generic
from bs4 import BeautifulSoup

T = TypeVar("T")


class BaseParser(ABC, Generic[T]):
    """
    Abstract base class for HTML parsers.

    Provides common utilities for:
    - HTML parsing with BeautifulSoup
    - Date parsing
    - Text cleaning
    """

    def __init__(self, parser: str = "html.parser"):
        """
        Initialize the parser.

        Args:
            parser: BeautifulSoup parser to use. Options:
                   - "html.parser" (built-in, lenient)
                   - "lxml" (fast, requires lxml package)
                   - "html5lib" (most lenient, requires html5lib)
        """
        self._parser = parser

    @abstractmethod
    def parse(self, html_content: str) -> T:
        """
        Parse the HTML content and return the result.

        Args:
            html_content: Raw HTML string to parse

        Returns:
            Parsed result of type T
        """
        pass

    def _make_soup(self, html_content: str) -> BeautifulSoup:
        """Create a BeautifulSoup object from HTML content."""
        return BeautifulSoup(html_content, self._parser)

    def _parse_date(self, date_str: str, format: str = "%d/%m/%Y") -> Optional[datetime]:
        """
        Parse a date string.

        Args:
            date_str: Date string to parse
            format: Expected date format (default: DD/MM/YYYY)

        Returns:
            Parsed datetime or None if parsing fails
        """
        if not date_str:
            return None
        try:
            # Clean the string first
            cleaned = date_str.strip()
            # Handle datetime with time component
            if " " in cleaned and ":" in cleaned:
                # Try DD/MM/YYYY HH:MM:SS format
                try:
                    return datetime.strptime(cleaned, "%d/%m/%Y %H:%M:%S")
                except ValueError:
                    # Fall back to date only
                    cleaned = cleaned.split()[0]
            return datetime.strptime(cleaned, format)
        except ValueError:
            return None

    def _clean_text(self, text: Optional[str]) -> str:
        """
        Clean text by removing extra whitespace and HTML entities.

        Args:
            text: Text to clean (can be None)

        Returns:
            Cleaned text string
        """
        if not text:
            return ""
        # Replace &nbsp; and other common entities
        cleaned = text.replace("\xa0", " ").replace("&nbsp;", " ")
        # Normalize whitespace
        return " ".join(cleaned.split())

    def _extract_text_safe(self, element) -> str:
        """
        Safely extract text from a BeautifulSoup element.

        Args:
            element: BeautifulSoup element (can be None)

        Returns:
            Extracted and cleaned text
        """
        if element is None:
            return ""
        return self._clean_text(element.get_text())
