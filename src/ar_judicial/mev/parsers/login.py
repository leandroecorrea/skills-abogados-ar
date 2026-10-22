"""Parser for MEV login response page."""

from dataclasses import dataclass
from typing import Optional

from .base import BaseParser


@dataclass
class ParsedUser:
    """User data extracted from login response."""

    username: str
    fullname: str


class LoginPageParser(BaseParser[Optional[ParsedUser]]):
    """
    Parser for the MEV login response page.

    Extracts user information from the response HTML after successful login.

    Expected HTML structure:
        <p class='whiteleft'>
            UsuarioMEV:&nbsp;<b>username</b>...
            Nombre:&nbsp;<b>fullname</b>
        </p>
    """

    def parse(self, html_content: str) -> Optional[ParsedUser]:
        """
        Parse the login response to extract user data.

        Args:
            html_content: HTML response from login

        Returns:
            ParsedUser with username and fullname, or None if not found
        """
        soup = self._make_soup(html_content)

        # Find paragraphs with class 'whiteleft' containing 'UsuarioMEV'
        white_left_paragraphs = soup.find_all("p", class_="whiteleft")

        for p in white_left_paragraphs:
            text = p.get_text()
            if "UsuarioMEV" in text:
                bold_tags = p.find_all("b")
                if len(bold_tags) >= 2:
                    username = self._clean_text(bold_tags[0].get_text())
                    fullname = self._clean_text(bold_tags[-1].get_text())
                    return ParsedUser(username=username, fullname=fullname)

        return None

    def is_login_successful(self, html_content: str) -> bool:
        """
        Check if the login was successful.

        Args:
            html_content: HTML response from login

        Returns:
            True if login was successful
        """
        return self.parse(html_content) is not None

    def extract_error_message(self, html_content: str) -> Optional[str]:
        """
        Extract error message from failed login response.

        Args:
            html_content: HTML response from login

        Returns:
            Error message if present, None otherwise
        """
        soup = self._make_soup(html_content)

        # Look for common error indicators
        error_indicators = [
            soup.find("p", class_="error"),
            soup.find("div", class_="error"),
            soup.find(string=lambda t: t and "incorrecto" in t.lower()),
            soup.find(string=lambda t: t and "invalido" in t.lower()),
        ]

        for indicator in error_indicators:
            if indicator:
                return self._extract_text_safe(indicator)

        return None
