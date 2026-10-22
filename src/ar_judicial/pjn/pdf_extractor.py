"""
PDF Text Extraction for PJN documents.

Uses a fallback chain:
1. PyMuPDF (fitz) for text-based PDFs - fast, free
2. pdf2image + pytesseract for scanned documents - slower, requires tesseract

When both fail, the PDF is still saved to disk so Claude can read it directly.
"""

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Check for required packages
try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    logger.warning("PyMuPDF not installed. Run: pip install pymupdf")

try:
    from pdf2image import convert_from_bytes
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    logger.info("pdf2image/pytesseract not installed. Scanned PDFs won't be processed.")


@dataclass
class ExtractionResult:
    """Result of PDF text extraction."""

    text: str
    pages: int
    method: str  # "pymupdf", "tesseract", "gemini_vision", "none"
    has_text: bool
    metadata: dict

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "pages": self.pages,
            "method": self.method,
            "has_text": self.has_text,
            "metadata": self.metadata,
        }


class PDFExtractor:
    """
    Extracts text from PDF documents.

    Uses PyMuPDF for direct extraction, falls back to pdf2image+tesseract for scanned docs.
    """

    # Minimum characters to consider extraction successful
    MIN_TEXT_CHARS = 50

    def __init__(self, ocr_language: str = "spa", ocr_dpi: int = 200):
        """
        Initialize the extractor.

        Args:
            ocr_language: Language for OCR (default: Spanish)
            ocr_dpi: DPI for PDF to image conversion (default: 200, higher = better quality but slower)
        """
        self.ocr_language = ocr_language
        self.ocr_dpi = ocr_dpi

        if not PYMUPDF_AVAILABLE:
            raise RuntimeError("PyMuPDF is required. Install with: pip install pymupdf")

    def extract_from_bytes(self, pdf_bytes: bytes) -> ExtractionResult:
        """
        Extract text from PDF bytes.

        Args:
            pdf_bytes: Raw PDF content

        Returns:
            ExtractionResult with extracted text and metadata
        """
        # Try PyMuPDF first
        result = self._extract_with_pymupdf(pdf_bytes)

        # If no meaningful text, try OCR
        if not result.has_text and OCR_AVAILABLE:
            logger.info(f"No text found, attempting OCR ({result.pages} pages)...")
            result = self._extract_with_tesseract(pdf_bytes, result.metadata)

        return result

    def extract_from_file(self, pdf_path: Path) -> ExtractionResult:
        """
        Extract text from PDF file.

        Args:
            pdf_path: Path to PDF file

        Returns:
            ExtractionResult with extracted text and metadata
        """
        pdf_bytes = pdf_path.read_bytes()
        return self.extract_from_bytes(pdf_bytes)

    def _extract_with_pymupdf(self, pdf_bytes: bytes) -> ExtractionResult:
        """Direct text extraction using PyMuPDF."""
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")

            metadata = {
                "title": doc.metadata.get("title", ""),
                "author": doc.metadata.get("author", ""),
                "creator": doc.metadata.get("creator", ""),
                "producer": doc.metadata.get("producer", ""),
                "creation_date": doc.metadata.get("creationDate", ""),
            }

            num_pages = len(doc)
            text_parts = []
            for page in doc:
                page_text = page.get_text()
                if page_text.strip():
                    text_parts.append(page_text)

            doc.close()

            full_text = "\n\n".join(text_parts)
            has_text = self._has_meaningful_text(full_text)

            return ExtractionResult(
                text=full_text if has_text else "",
                pages=num_pages,
                method="pymupdf",
                has_text=has_text,
                metadata=metadata,
            )

        except Exception as e:
            logger.error(f"PyMuPDF extraction failed: {e}")
            return ExtractionResult(
                text="",
                pages=0,
                method="none",
                has_text=False,
                metadata={"error": str(e)},
            )

    def _extract_with_tesseract(self, pdf_bytes: bytes, existing_metadata: dict) -> ExtractionResult:
        """OCR extraction using pdf2image + pytesseract."""
        if not OCR_AVAILABLE:
            return ExtractionResult(
                text="",
                pages=0,
                method="none",
                has_text=False,
                metadata={**existing_metadata, "ocr_error": "pdf2image/pytesseract not installed"},
            )

        try:
            # Convert PDF pages to images
            images = convert_from_bytes(pdf_bytes, dpi=self.ocr_dpi)
            num_pages = len(images)

            logger.info(f"OCR: Converting {num_pages} pages at {self.ocr_dpi} DPI...")

            # Extract text from each page
            text_parts = []
            for i, img in enumerate(images):
                page_text = pytesseract.image_to_string(img, lang=self.ocr_language)
                if page_text.strip():
                    text_parts.append(page_text)
                logger.debug(f"OCR page {i+1}: {len(page_text)} chars")

            full_text = "\n\n".join(text_parts)
            has_text = self._has_meaningful_text(full_text)

            logger.info(f"OCR complete: {len(full_text)} chars extracted")

            return ExtractionResult(
                text=full_text if has_text else "",
                pages=num_pages,
                method="tesseract",
                has_text=has_text,
                metadata={**existing_metadata, "ocr_applied": True, "ocr_dpi": self.ocr_dpi},
            )

        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
            return ExtractionResult(
                text="",
                pages=0,
                method="none",
                has_text=False,
                metadata={**existing_metadata, "ocr_error": str(e)},
            )

    def _has_meaningful_text(self, text: str) -> bool:
        """Check if text has meaningful content."""
        if not text:
            return False

        # Remove whitespace and count alphanumeric chars
        cleaned = "".join(c for c in text if c.isalnum())
        return len(cleaned) >= self.MIN_TEXT_CHARS

    @staticmethod
    def is_ocr_available() -> bool:
        """Check if OCR is available."""
        return OCR_AVAILABLE
