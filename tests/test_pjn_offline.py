"""Offline tests for the PJN CLI wiring and rendering (no network)."""

import pytest

from ar_judicial import cli, render
from ar_judicial.pjn.fetch import ActuacionConTexto, ExpedientePJN
from ar_judicial.pjn.models import (
    Actuacion,
    ExpedienteDetail,
    Interviniente,
    IntervinientesList,
    Letrado,
)


@pytest.mark.parametrize("value,code", [("CIV", "1"), ("civ", "1"), ("7", "7"), ("seguridad social", "5"), ("FLP", "18")])
def test_resolve_jurisdiction(value, code):
    assert cli._resolve_jurisdiction(value) == code


def test_resolve_jurisdiction_ambiguous():
    with pytest.raises(SystemExit):
        cli._resolve_jurisdiction("justicia federal")


def test_jurisdicciones_command(capsys):
    assert cli.main(["mev", "departamentos"]) == 0
    capsys.readouterr()
    assert cli.main(["pjn", "jurisdicciones"]) == 0
    out = capsys.readouterr().out
    assert "| 1 | CIV |" in out and "FTU" in out


def _expediente(with_text: bool) -> ExpedientePJN:
    acts = [
        Actuacion(oficina="051", fecha="10/03/2025", tipo="FIRMA DESPACHO", descripcion="TRASLADO",
                  documento_download_url="/scw/viewer.seam?id=x&download=true", documento_tipo="despacho"),
        Actuacion(oficina="051", fecha="3/02/2025", tipo="ESCRITO AGREGADO", descripcion="DEMANDA"),
    ]
    items = [
        ActuacionConTexto(actuacion=acts[0], texto="Córrase traslado por 15 días." if with_text else None,
                          archivo="/tmp/x.pdf" if with_text else None),
        ActuacionConTexto(actuacion=acts[1]),
    ]
    partes = IntervinientesList(partes=[
        Interviniente(tipo="ACTOR", nombre="PEREZ JUAN",
                      letrados=[Letrado(tipo="LETRADO PATROCINANTE", nombre="GOMEZ ANA", tomo_folio="T 1 F 2")]),
    ])
    datos = ExpedienteDetail(numero="CIV 008078/2025", jurisdiccion="Cámara Civil",
                             dependencia="JUZGADO CIVIL 88", situacion="EN LETRA", caratula="PEREZ C/ GOMEZ")
    return ExpedientePJN(datos=datos, actuaciones=items, intervinientes=partes)


def test_render_expediente_table_is_chronological():
    md = render.pjn_expediente(_expediente(with_text=False))
    assert "CIV 008078/2025" in md and "ACTOR:** PEREZ JUAN" in md and "GOMEZ ANA (T 1 F 2)" in md
    assert md.index("DEMANDA") < md.index("TRASLADO")


def test_render_expediente_with_documents():
    md = render.pjn_expediente(_expediente(with_text=True))
    assert "### 10/03/2025 — FIRMA DESPACHO" in md
    assert "Córrase traslado por 15 días." in md
    assert "PDF: /tmp/x.pdf" in md


def test_to_dict_roundtrip():
    d = _expediente(with_text=True).to_dict()
    assert d["total_actuaciones"] == 2
    assert d["intervinientes"]["partes"][0]["letrados"][0]["nombre"] == "GOMEZ ANA"


class _FakeResponse:
    def __init__(self, content: bytes):
        self.content = content


class _FakeClient:
    def __init__(self):
        self.calls = []

    async def download_document(self, url):
        self.calls.append(url)
        if "boom" in url:
            raise RuntimeError("HTTP 500")
        return _FakeResponse(b"%PDF-1.4 " + b"x" * 200)


def test_download_documents_saves_pdfs_and_keeps_going(tmp_path):
    import asyncio

    from ar_judicial.pjn.fetch import download_documents

    acts = [
        Actuacion(oficina="1", fecha="3/02/2025 10:00", tipo="FIRMA DESPACHO", descripcion="",
                  documento_download_url="/ok"),
        Actuacion(oficina="1", fecha="4/02/2025", tipo="CEDULA", descripcion="", documento_download_url="/boom"),
        Actuacion(oficina="1", fecha="5/02/2025", tipo="MOVIMIENTO", descripcion=""),
    ]
    client = _FakeClient()
    items = asyncio.run(download_documents(client, acts, tmp_path / "docs", extract_text=False))
    assert client.calls == ["/ok", "/boom"]
    assert items[0].archivo.endswith("0000_3-02-2025_FIRMA_DESPACHO.pdf")
    assert (tmp_path / "docs").joinpath(items[0].archivo.split("/")[-1]).exists()
    assert items[1].error == "HTTP 500" and items[1].archivo is None
    assert items[2].archivo is None and items[2].error is None
