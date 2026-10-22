"""Command line interface: `ar-judicial <sistema> <comando>`.

Output is Markdown by default (easy for Claude and humans to read) or JSON
with --json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from . import catalog, credentials, render
from .mev import (
    CourtFileRequest,
    Credentials,
    FileOrderRequest,
    MEVError,
    MEVService,
    SearchFamiliaRequest,
)


def _slug(text: str, max_len: int = 60) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)[:max_len].strip("-") or "causa"


def _mev_credentials() -> Credentials:
    usuario, clave = credentials.require("MEV_USUARIO", "MEV_CLAVE")
    return Credentials(username=usuario, password=clave)


def _resolve_district(args: argparse.Namespace) -> str:
    """Departamento may be omitted when the juzgado code identifies it."""
    if args.departamento:
        matches = catalog.find_districts(args.departamento)
        if len(matches) != 1:
            raise SystemExit(
                f"Departamento '{args.departamento}' ambiguo o inexistente. "
                "Usá `ar-judicial mev departamentos`."
            )
        return matches[0].tracking_code
    d = catalog.district_for_court(args.juzgado)
    if d is None:
        raise SystemExit(
            f"No encuentro el juzgado '{args.juzgado}' en el catálogo; indicá --departamento."
        )
    return d.tracking_code


def _emit(args: argparse.Namespace, data, markdown: str) -> None:
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    else:
        print(markdown)


# ---------------------------------------------------------------------------
# MEV commands
# ---------------------------------------------------------------------------


def cmd_departamentos(args):
    ds = catalog.find_districts(args.buscar)
    data = [{"codigo": d.tracking_code, "nombre": d.district_name, "juzgados": len(d.courts)} for d in ds]
    md = "| Código | Departamento | Juzgados |\n|---|---|---|\n" + "\n".join(
        f"| {x['codigo']} | {x['nombre']} | {x['juzgados']} |" for x in data
    )
    _emit(args, data, md)


def cmd_juzgados(args):
    pairs = catalog.find_courts(args.buscar, args.departamento)
    data = [
        {"codigo": c.query_code, "nombre": c.fullname, "departamento": d.district_name, "departamento_codigo": d.tracking_code}
        for d, c in pairs
    ]
    md = "| Código | Juzgado | Departamento (código) |\n|---|---|---|\n" + "\n".join(
        f"| {x['codigo']} | {x['nombre']} | {x['departamento']} ({x['departamento_codigo']}) |" for x in data
    )
    _emit(args, data, md or "_Sin resultados._")


async def cmd_buscar(args):
    district = _resolve_district(args)
    creds = _mev_credentials()
    async with MEVService() as mev:
        if args.numero:
            files = await mev.search_by_case_number(creds, district, args.juzgado, args.numero)
        else:
            files = await mev.search_by_caption(creds, district, args.juzgado, args.caratula)
    _emit(args, [f.to_dict() for f in files], render.causas_table(files))


async def cmd_familia(args):
    district = _resolve_district(args)
    creds = _mev_credentials()
    async with MEVService() as mev:
        files = await mev.search_familia_files(SearchFamiliaRequest(credentials=creds, district_code=district))
    _emit(args, [f.to_dict() for f in files], render.causas_table(files))


async def cmd_causa(args):
    district = _resolve_district(args)
    creds = _mev_credentials()
    request = CourtFileRequest(
        credentials=creds, district_code=district, court_id=args.juzgado, case_id=args.causa
    )
    async with MEVService() as mev:
        if args.completa:
            result = await mev.download_causa_context(request)
            markdown = render.causa_context(result)
            caption = result.file.case_caption
        else:
            result = await mev.download_file(request)
            markdown = render.full_file(result)
            caption = result.file.case_caption

    if args.salida:
        out = Path(args.salida).expanduser() / f"{_slug(caption)}-{args.causa}"
        out.mkdir(parents=True, exist_ok=True)
        (out / "expediente.md").write_text(markdown, encoding="utf-8")
        (out / "expediente.json").write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(f"Guardado en {out}/expediente.md y expediente.json")
        return
    _emit(args, result.to_dict(), markdown)


async def cmd_proveido(args):
    district = _resolve_district(args)
    creds = _mev_credentials()
    async with MEVService() as mev:
        order = await mev.read_order(
            FileOrderRequest(
                credentials=creds,
                district_code=district,
                court_id=args.juzgado,
                order_code=args.codigo,
                position=args.posicion,
                file_type=args.tipo,
            )
        )
    md = f"# {order.datetime_formatted} — {order.title}\n\n"
    if order.signed_by:
        md += f"_Firmado por: {order.signed_by}_\n\n"
    md += order.text.strip() + "\n"
    if order.attachments:
        md += "\n## Adjuntos\n\n" + "\n".join(f"- [{a.name}]({a.url})" for a in order.attachments) + "\n"
    _emit(args, order.to_dict(), md)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ar-judicial", description="Consulta de sistemas judiciales argentinos.")
    p.add_argument("--json", action="store_true", help="Salida en JSON en lugar de Markdown")
    systems = p.add_subparsers(dest="sistema", required=True)

    mev = systems.add_parser("mev", help="Mesa de Entradas Virtual (SCBA, Provincia de Buenos Aires)")
    sub = mev.add_subparsers(dest="comando", required=True)

    s = sub.add_parser("departamentos", help="Listar departamentos judiciales (sin login)")
    s.add_argument("--buscar", help="Filtrar por nombre o código")
    s.set_defaults(func=cmd_departamentos)

    s = sub.add_parser("juzgados", help="Buscar juzgados y sus códigos (sin login)")
    s.add_argument("--buscar", help='Ej: "civil 1 avellaneda", "familia 2 la plata"')
    s.add_argument("--departamento", help="Nombre o código del departamento")
    s.set_defaults(func=cmd_juzgados)

    def juzgado_args(sp, juzgado_required=True):
        sp.add_argument("--juzgado", required=juzgado_required, help="Código MEV del juzgado (ej. GAM2078)")
        sp.add_argument("--departamento", help="Nombre o código; se deduce del juzgado si se omite")

    s = sub.add_parser("buscar", help="Buscar causas en un juzgado por número o carátula")
    juzgado_args(s)
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--numero", help="Número de causa")
    g.add_argument("--caratula", help="Texto de la carátula")
    s.set_defaults(func=cmd_buscar)

    s = sub.add_parser("familia", help="Listar causas autorizadas del fuero de Familia en un departamento")
    s.add_argument("--departamento", required=True)
    s.add_argument("--juzgado", help=argparse.SUPPRESS)
    s.set_defaults(func=cmd_familia)

    s = sub.add_parser("causa", help="Descargar una causa (lista de trámites o expediente completo)")
    juzgado_args(s)
    s.add_argument("--causa", required=True, help="nidCausa (columna nidCausa de `buscar`)")
    s.add_argument("--completa", action="store_true", help="Incluir el texto de cada proveído (más lento)")
    s.add_argument("--salida", help="Carpeta donde guardar expediente.md y expediente.json")
    s.set_defaults(func=cmd_causa)

    s = sub.add_parser("proveido", help="Leer el texto completo de un proveído")
    juzgado_args(s)
    s.add_argument("--codigo", required=True, help="sCodi (normalmente igual al nidCausa)")
    s.add_argument("--posicion", required=True, help="nPosi del trámite")
    s.add_argument("--tipo", default="a", help="sFile (por defecto 'a')")
    s.set_defaults(func=cmd_proveido)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = args.func(args)
        if asyncio.iscoroutine(result):
            asyncio.run(result)
    except credentials.MissingCredentialsError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except MEVError as e:
        print(f"Error de MEV: {e.message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
