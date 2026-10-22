"""Offline tests: catalog, credentials, rendering and CLI wiring (no network)."""

from datetime import datetime

import pytest

from ar_judicial import catalog, cli, credentials, render
from ar_judicial.mev.models import CausaContext, CourtFile, OrderWithText


def test_catalog_loads_all_districts():
    districts = catalog.load_districts()
    assert len(districts) == 23
    assert sum(len(d.courts) for d in districts) == 345


def test_find_district_by_name_and_code():
    assert [d.tracking_code for d in catalog.find_districts("avellaneda")] == ["80"]
    assert [d.district_name for d in catalog.find_districts("80")] == ["Avellaneda-Lanus"]
    assert len(catalog.find_districts("bahia blanca")) == 1  # accent-insensitive


def test_find_courts_numbers_match_exactly():
    codes = [c.query_code for _, c in catalog.find_courts("civil 1 avellaneda")]
    assert "GAM2078" in codes
    names = [c.fullname for _, c in catalog.find_courts("civil 1 avellaneda")]
    assert all("N° 1 " in n or n.endswith("N° 1") for n in names)


def test_district_for_court():
    assert catalog.district_for_court("GAM2078").tracking_code == "80"
    assert catalog.district_for_court("NOPE") is None


def test_env_file_parsing(tmp_path, monkeypatch):
    env = tmp_path / "creds.env"
    env.write_text('# comment\nexport MEV_USUARIO="juan"\nMEV_PASSWORD=secreto\n', encoding="utf-8")
    for k in ("MEV_USUARIO", "MEV_USERNAME", "MEV_CLAVE", "MEV_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AR_JUDICIAL_ENV", str(env))
    assert credentials.require("MEV_USUARIO", "MEV_CLAVE") == ["juan", "secreto"]


def test_missing_credentials_exit_code(tmp_path, monkeypatch):
    for k in ("MEV_USUARIO", "MEV_USERNAME", "MEV_CLAVE", "MEV_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AR_JUDICIAL_ENV", str(tmp_path / "missing.env"))
    monkeypatch.setattr(credentials, "CONFIG_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["mev", "buscar", "--juzgado", "GAM2078", "--numero", "1"]) == 2


def test_cli_juzgados_json(capsys):
    assert cli.main(["--json", "mev", "juzgados", "--buscar", "civil 1 avellaneda"]) == 0
    assert "GAM2078" in capsys.readouterr().out


def test_render_causa_context_is_chronological():
    file = CourtFile(id="1", court_id="GAM2078", case_caption="PEREZ C/ GOMEZ S/ DAÑOS",
                     status="", reception_number="", file_number="123")
    ctx = CausaContext(file=file, court_name="Civil 1", district_name="Avellaneda", orders=[
        OrderWithText(date=datetime(2024, 3, 1), title="SENTENCIA", text="Fallo"),
        OrderWithText(date=datetime(2024, 1, 1), title="DEMANDA", text="Se presenta"),
        OrderWithText(date=datetime(2024, 2, 1), title="TRASLADO", text="", error="timeout"),
    ])
    md = render.causa_context(ctx)
    assert md.index("DEMANDA") < md.index("TRASLADO") < md.index("SENTENCIA")
    assert "No se pudo descargar el texto: timeout" in md


def test_unknown_court_without_department_fails():
    with pytest.raises(SystemExit):
        cli.main(["mev", "causa", "--juzgado", "XXX", "--causa", "1"])
