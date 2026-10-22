# CLAUDE.md

Claude skills + the `ar-judicial` Python package for Argentine lawyers to query court systems
(MEV/SCBA today; PJN and Portal de Notificaciones planned) with their own credentials.

## Layout

- `src/ar_judicial/<sistema>/`: HTTP client, HTML parsers and models per court system. Ported
  from Funes (`apps/api/app/services/<sistema>/`); keep them free of any database or LLM code.
- `src/ar_judicial/cli.py`: `ar-judicial <sistema> <comando>`. Markdown output by default, `--json` optional.
- `skills/<name>/SKILL.md`: one skill per court system. Skills only call the CLI; they never scrape directly.
- `.claude-plugin/`: plugin + marketplace manifests (repo root is the plugin).

## Rules

- Credentials are read only from env vars or `~/.config/ar-judicial/.env`. Never log, print or
  include them in exception messages, and skills must never ask users to paste them into chat.
- Captchas (e.g. PJN SCW search) are solved by the human: the CLI saves the image and asks the
  user to type the answer. Do not automate captcha solving.
- No parallel or bulk requests against court systems; keep retry counts low.
- Language: Spanish for user-facing text (CLI output, skills, README); English for code and comments.

## Commands

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/pytest          # offline tests, no credentials needed
```
