"""Fetch a full PJN expediente from its SCW detail page.

Ported from Funes' PJNFetcher (pipeline/fetchers/pjn.py) and the PJN router's
detail parsing, without the database/pipeline types.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .models import Actuacion, ExpedienteDetail, IntervinientesList
from .parsers import ExpedienteDetailParser, _extract_main_cdata, _extract_view_state_from_ajax

logger = logging.getLogger(__name__)

PDF_DOWNLOAD_TIMEOUT = 60  # seconds per document (download + extraction)


@dataclass
class ActuacionConTexto:
    actuacion: Actuacion
    texto: Optional[str] = None  # Extracted PDF text, if any
    archivo: Optional[str] = None  # Saved PDF path, if any
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            **self.actuacion.to_dict(),
            "texto": self.texto,
            "archivo": self.archivo,
            "error": self.error,
        }


@dataclass
class ExpedientePJN:
    datos: Optional[ExpedienteDetail]
    actuaciones: list[ActuacionConTexto] = field(default_factory=list)
    intervinientes: Optional[IntervinientesList] = None

    def to_dict(self) -> dict:
        return {
            "datos_generales": self.datos.to_dict() if self.datos else None,
            "actuaciones": [a.to_dict() for a in self.actuaciones],
            "total_actuaciones": len(self.actuaciones),
            "intervinientes": self.intervinientes.to_dict() if self.intervinientes else None,
        }


async def fetch_all_actuaciones(
    http_client,
    detail_parser: ExpedienteDetailParser,
    detail_html: str,
    detail_url: str,
    max_pages: int = 200,
) -> tuple[list[Actuacion], Optional[str], Optional[str]]:
    """
    Fetch all actuaciones from a detail page following the "Siguiente" button.

    PJN shows a sliding window of numbered page links, so "Siguiente" is more
    reliable than iterating numbered page IDs.

    Returns (all_actuaciones, cid, view_state of the first page).
    """
    cid = detail_parser.extract_cid(detail_url)
    view_state = detail_parser.extract_view_state(detail_html)

    all_actuaciones = list(detail_parser.parse_actuaciones(detail_html).actuaciones)

    current_html = detail_html
    current_view_state = view_state

    for _ in range(max_pages):
        siguiente_id = detail_parser.extract_siguiente_id(current_html)
        if not siguiente_id:
            break

        await asyncio.sleep(0.3)  # Be gentle with SCW
        response = await http_client.fetch_actuaciones_page(
            cid=cid,
            view_state=current_view_state,
            page_element_id=siguiente_id,
        )
        if response.status_code != 200:
            break

        all_actuaciones.extend(detail_parser.parse_actuaciones_from_ajax(response.text).actuaciones)

        new_vs = _extract_view_state_from_ajax(response.text)
        if new_vs:
            current_view_state = new_vs

        main_html = _extract_main_cdata(response.text)
        if not main_html:
            break
        current_html = main_html

    return all_actuaciones, cid, view_state


def _safe_filename(text: str, max_len: int = 50) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip()
    return re.sub(r"[\s]+", "_", text)[:max_len] or "documento"


async def download_documents(
    http_client,
    actuaciones: list[Actuacion],
    documentos_dir: Path,
    extract_text: bool = True,
) -> list[ActuacionConTexto]:
    """Download every attached PDF sequentially, save it and extract its text."""
    extractor = None
    if extract_text:
        try:
            from .pdf_extractor import PDFExtractor

            extractor = PDFExtractor(ocr_language="spa")
        except RuntimeError:
            logger.warning("PyMuPDF no instalado: se guardan los PDFs sin extraer texto")

    documentos_dir.mkdir(parents=True, exist_ok=True)
    results: list[ActuacionConTexto] = []

    for i, act in enumerate(actuaciones):
        item = ActuacionConTexto(actuacion=act)
        if act.documento_download_url:
            try:
                async def _download(a=act) -> bytes:
                    response = await http_client.download_document(a.documento_download_url)
                    return response.content

                pdf_bytes = await asyncio.wait_for(_download(), timeout=PDF_DOWNLOAD_TIMEOUT)
                if pdf_bytes and len(pdf_bytes) > 100:
                    fecha = act.fecha.replace("/", "-").split(" ")[0]
                    path = documentos_dir / f"{i:04d}_{fecha}_{_safe_filename(act.tipo)}.pdf"
                    path.write_bytes(pdf_bytes)
                    item.archivo = str(path)
                    if extractor is not None:
                        result = await asyncio.to_thread(extractor.extract_from_bytes, pdf_bytes)
                        if result.has_text:
                            item.texto = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", result.text)
            except asyncio.TimeoutError:
                item.error = f"Timeout ({PDF_DOWNLOAD_TIMEOUT}s)"
            except Exception as e:  # keep going with the rest of the documents
                item.error = str(e)
        results.append(item)

    return results


async def fetch_expediente(
    http_client,
    detail_html: str,
    detail_url: str,
    documentos_dir: Optional[Path] = None,
) -> ExpedientePJN:
    """Datos generales + all actuaciones + intervinientes (+ PDFs if documentos_dir)."""
    parser = ExpedienteDetailParser()
    datos = parser.parse_datos_generales(detail_html)

    actuaciones, cid, view_state = await fetch_all_actuaciones(http_client, parser, detail_html, detail_url)

    intervinientes = None
    try:
        interv_response = await http_client.fetch_intervinientes_tab(cid=cid, view_state=view_state)
        intervinientes = parser.parse_intervinientes(interv_response.text)
    except Exception as e:
        logger.warning(f"No se pudieron obtener los intervinientes: {e}")

    if documentos_dir is not None:
        items = await download_documents(http_client, actuaciones, documentos_dir)
    else:
        items = [ActuacionConTexto(actuacion=a) for a in actuaciones]

    return ExpedientePJN(datos=datos, actuaciones=items, intervinientes=intervinientes)
