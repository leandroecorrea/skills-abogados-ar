"""Render court data as Markdown, the format Claude reads best."""

from __future__ import annotations

from datetime import datetime

from .mev.models import CausaContext, CourtFile, FullCourtFile


def causas_table(files: list[CourtFile]) -> str:
    if not files:
        return "_Sin resultados._\n"
    lines = [
        "| Carátula | Expediente | Receptoría | Estado | Último movimiento | Juzgado | nidCausa |",
        "|---|---|---|---|---|---|---|",
    ]
    for f in files:
        ultimo = f"{f.last_update_formatted} {f.last_order_title}".strip()
        cells = [f.case_caption, f.file_number, f.reception_number, f.status, ultimo, f.court_name or f.court_id, f.id]
        lines.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
    return "\n".join(lines) + "\n"


def _header(file: CourtFile, court_name: str, district_name: str) -> list[str]:
    return [
        f"# {file.case_caption or 'Causa ' + file.id}",
        "",
        f"- **Juzgado:** {court_name or file.court_id}",
        f"- **Departamento judicial:** {district_name or '-'}",
        f"- **Expediente:** {file.file_number or '-'}",
        f"- **Receptoría:** {file.reception_number or '-'}",
        f"- **Estado:** {file.status or '-'}",
        f"- **Inicio:** {file.initial_date_formatted}",
        f"- **MEV:** nidCausa={file.id} · pidJuzgado={file.court_id}",
        "",
    ]


def full_file(ff: FullCourtFile) -> str:
    lines = _header(ff.file, ff.court_name, ff.district_name)
    lines += [f"## Trámites ({ff.order_count})", "", "| Fecha | Trámite | Fojas | Firmado | nPosi |", "|---|---|---|---|---|"]
    for o in sorted(ff.orders, key=lambda o: o.date, reverse=True):
        lines.append(f"| {o.datetime_formatted} | {o.title} | {o.fojas or '-'} | {'sí' if o.is_signed else 'no'} | {o.position} |")
    return "\n".join(lines) + "\n"


def causa_context(ctx: CausaContext) -> str:
    """Full expediente: header plus every proveído text, oldest first."""
    lines = _header(ctx.file, ctx.court_name, ctx.district_name)
    lines += [f"## Proveídos ({ctx.order_count})", ""]
    for o in sorted(ctx.orders, key=lambda o: o.date):
        lines.append(f"### {o.datetime_formatted} — {o.title}")
        meta = []
        if o.fojas:
            meta.append(f"Fojas: {o.fojas}")
        if o.signed_by:
            meta.append(f"Firmado por: {o.signed_by}")
        if meta:
            lines += ["", "_" + " · ".join(meta) + "_"]
        lines.append("")
        if o.error:
            lines.append(f"> No se pudo descargar el texto: {o.error}")
        else:
            lines.append(o.text.strip() or "_(sin texto)_")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# PJN
# ---------------------------------------------------------------------------


def _cell(text) -> str:
    return (str(text) if text is not None else "").replace("|", "/").replace("\n", " ").strip()


def pjn_expedientes_table(rows: list[tuple[str, object]]) -> str:
    """rows: (perfil, Expediente | SCWResult)."""
    if not rows:
        return "_Sin resultados._\n"
    lines = [
        "| # | Número | Carátula | Dependencia | Situación | Últ. actualización | Perfil |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, (perfil, e) in enumerate(rows):
        cells = [i, e.numero, e.caratula, e.dependencia, e.situacion, e.ultima_actualizacion, perfil]
        lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    return "\n".join(lines) + "\n"


def _pjn_date(fecha: str) -> datetime:
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime((fecha or "").strip(), fmt)
        except ValueError:
            continue
    return datetime.min


def pjn_expediente(exp) -> str:
    """Render an ExpedientePJN: datos generales, partes and actuaciones (oldest first)."""
    d = exp.datos
    lines = [f"# {d.caratula if d else 'Expediente PJN'}", ""]
    if d:
        lines += [
            f"- **Número:** {d.numero}",
            f"- **Jurisdicción:** {d.jurisdiccion}",
            f"- **Dependencia:** {d.dependencia}",
            f"- **Situación:** {d.situacion}",
            "",
        ]

    if exp.intervinientes and (exp.intervinientes.partes or exp.intervinientes.fiscales):
        lines += ["## Intervinientes", ""]
        for p in exp.intervinientes.partes:
            lines.append(f"- **{p.tipo}:** {p.nombre}")
            for l in p.letrados:
                extra = f" ({l.tomo_folio})" if l.tomo_folio else ""
                lines.append(f"  - {l.tipo}: {l.nombre}{extra}")
        for f in exp.intervinientes.fiscales:
            lines.append(f"- **FISCALÍA:** {f.fiscalia} — {f.fiscal}")
        lines.append("")

    items = sorted(exp.actuaciones, key=lambda a: _pjn_date(a.actuacion.fecha))
    lines += [f"## Actuaciones ({len(items)})", ""]
    with_text = any(a.texto or a.archivo or a.error for a in items)
    if not with_text:
        lines += ["| Fecha | Tipo | Descripción | Fojas | Oficina | Doc. |", "|---|---|---|---|---|---|"]
        for a in items:
            act = a.actuacion
            doc = act.documento_tipo or ("sí" if act.documento_download_url else "")
            lines.append(
                "| " + " | ".join(_cell(c) for c in [act.fecha, act.tipo, act.descripcion, act.fojas or "", act.oficina, doc]) + " |"
            )
        return "\n".join(lines) + "\n"

    for a in items:
        act = a.actuacion
        lines.append(f"### {act.fecha} — {act.tipo}")
        lines.append("")
        if act.descripcion and act.descripcion != act.tipo:
            lines += [act.descripcion, ""]
        meta = [m for m in [f"Fojas: {act.fojas}" if act.fojas else "", f"Oficina: {act.oficina}" if act.oficina else "",
                            f"PDF: {a.archivo}" if a.archivo else ""] if m]
        if meta:
            lines += ["_" + " · ".join(meta) + "_", ""]
        if a.texto:
            lines += [a.texto.strip(), ""]
        elif a.error:
            lines += [f"> No se pudo descargar el documento: {a.error}", ""]
        elif a.archivo:
            lines += ["> PDF sin texto extraíble (posiblemente escaneado): leer el archivo directamente.", ""]
    return "\n".join(lines)
