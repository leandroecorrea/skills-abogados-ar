# CLAUDE.md

Claude skills + the `ar-judicial` Python package for Argentine lawyers to query court systems
(MEV/SCBA and PJN today; Portal de Notificaciones planned) with their own credentials.

## Layout

- `src/ar_judicial/<sistema>/`: HTTP client, HTML parsers and models per court system. Ported
  from Funes (`apps/api/app/services/<sistema>/`); keep them free of any database or LLM code.
- `src/ar_judicial/cli.py`: `ar-judicial <sistema> <comando>`. Markdown output by default, `--json` optional.
- `skills/<name>/SKILL.md`: one skill per court system. Skills only call the CLI; they never scrape directly.
- `.claude-plugin/`: plugin + marketplace manifests (repo root is the plugin).

## Rules

- Credentials are read only from env vars or `~/.config/ar-judicial/.env`. Never log, print or
  include them in exception messages, and skills must never ask users to paste them into chat.
- Captchas are never solved automatically. With an authenticated session PJN's SCW search does
  not ask for one; if a captcha ever appears, stop and tell the user to complete that step
  themselves on the official site.
- No parallel or bulk requests against court systems; keep retry counts low.
- Language: Spanish for user-facing text (CLI output, skills, README); English for code and comments.

## Commands

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/pytest          # offline tests, no credentials needed
```
