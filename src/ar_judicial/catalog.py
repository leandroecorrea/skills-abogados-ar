"""Static catalog of MEV departamentos judiciales and juzgados.

MEV needs two opaque codes for every operation: the departamento tracking code
(e.g. "80") and the juzgado code (e.g. "GAM2078"). This catalog maps them to
human names so users can say "Civil y Comercial 1 de Avellaneda".
"""

from __future__ import annotations

import json
import unicodedata
from functools import lru_cache
from importlib import resources

from .mev.models import Court, District


@lru_cache(maxsize=1)
def load_districts() -> list[District]:
    raw = resources.files("ar_judicial.data").joinpath("mev_juzgados.json").read_text(encoding="utf-8")
    return [District.from_scraped_dict(d) for d in json.loads(raw)]


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(text.lower().replace("°", " ").replace("º", " ").split())


def find_districts(query: str | None = None) -> list[District]:
    districts = load_districts()
    if not query:
        return districts
    q = _norm(query)
    return [d for d in districts if q == d.tracking_code or q in _norm(d.district_name)]


_STOPWORDS = {"n", "nro", "no", "numero", "de", "del", "y", "en"}


def _matches(word: str, tokens: list[str]) -> bool:
    # Numbers must match exactly ("1" must not match "12"); words by prefix.
    if word.isdigit():
        return word in tokens
    return any(t.startswith(word) for t in tokens)


def find_courts(query: str | None = None, district: str | None = None) -> list[tuple[District, Court]]:
    """Return (district, court) pairs whose names match every word of query."""
    words = [w for w in _norm(query or "").replace(".", " ").split() if w not in _STOPWORDS]
    results = []
    for d in find_districts(district):
        for c in d.courts:
            tokens = _norm(f"{c.fullname} {d.district_name} {c.query_code}").replace(".", " ").split()
            if all(_matches(w, tokens) for w in words):
                results.append((d, c))
    return results


def district_for_court(court_code: str) -> District | None:
    for d in load_districts():
        if any(c.query_code == court_code for c in d.courts):
            return d
    return None
