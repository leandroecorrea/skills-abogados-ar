"""Local credential loading.

Credentials never leave the lawyer's machine except towards the court system
itself. They are read from environment variables or from a .env-style file:

    1. Environment variables (MEV_USUARIO / MEV_CLAVE)
    2. $AR_JUDICIAL_ENV, if set
    3. ./.env
    4. ~/.config/ar-judicial/.env
"""

from __future__ import annotations

import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "ar-judicial"

# Funes historically used MEV_USERNAME / MEV_PASSWORD; accept both.
ALIASES = {
    "MEV_USUARIO": ("MEV_USUARIO", "MEV_USERNAME"),
    "MEV_CLAVE": ("MEV_CLAVE", "MEV_PASSWORD"),
}


class MissingCredentialsError(RuntimeError):
    pass


def _candidate_files() -> list[Path]:
    files = []
    if os.environ.get("AR_JUDICIAL_ENV"):
        files.append(Path(os.environ["AR_JUDICIAL_ENV"]).expanduser())
    files.append(Path.cwd() / ".env")
    files.append(CONFIG_DIR / ".env")
    return files


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def get(name: str) -> str | None:
    keys = ALIASES.get(name, (name,))
    for key in keys:
        if os.environ.get(key):
            return os.environ[key]
    for path in _candidate_files():
        if path.is_file():
            values = parse_env_file(path)
            for key in keys:
                if values.get(key):
                    return values[key]
    return None


def require(*names: str) -> list[str]:
    values = [get(n) for n in names]
    missing = [n for n, v in zip(names, values) if not v]
    if missing:
        raise MissingCredentialsError(
            "Faltan credenciales: "
            + ", ".join(missing)
            + f". Definilas como variables de entorno o en {CONFIG_DIR / '.env'}"
            " (ver README). No las pegues en el chat."
        )
    return values  # type: ignore[return-value]
