# Skills para abogados de Argentina

Skills de [Claude](https://claude.ai) y [Claude Code](https://claude.com/claude-code) para que
abogados de Argentina consulten, descarguen y analicen sus causas judiciales directamente
desde Claude, con sus propias credenciales y sin intermediarios.

El código de acceso a los sistemas judiciales proviene de **Funes**, un asistente legal para
abogados de Provincia de Buenos Aires y fuero federal, y se libera bajo licencia Apache 2.0.

## Qué incluye

| Skill | Sistema | Estado |
|---|---|---|
| [`mev-causas`](skills/mev-causas/SKILL.md) | MEV — Mesa de Entradas Virtual (SCBA) | ✅ Disponible |
| [`pjn-expedientes`](skills/pjn-expedientes/SKILL.md) | PJN — Poder Judicial de la Nación (SCW) | ✅ Disponible |
| `portal-notificaciones` | Portal de Notificaciones (SCBA) | 🚧 Próximamente |

Con `mev-causas` le podés pedir a Claude, por ejemplo:

- "Buscá la causa 14107 del Civil y Comercial 1 de Avellaneda."
- "Bajame el expediente completo y haceme un resumen con el estado procesal."
- "¿Cuál fue el último proveído y qué plazo podría estar corriendo?"
- "Listá mis causas de Familia en San Isidro."

Con `pjn-expedientes`:

- "Listá mis expedientes del PJN."
- "Bajame el CIV 008078/2025 con todos los PDFs y decime en qué etapa está."
- "Buscá en la Cámara Comercial los expedientes donde es parte ACME SA."

## Instalación

### 1. Instalar la herramienta `ar-judicial`

Requiere Python 3.10 o superior.

```bash
# con uv (recomendado)
uv tool install git+https://github.com/leandroecorrea/skills-abogados-ar

# o con pip
pip install git+https://github.com/leandroecorrea/skills-abogados-ar
```

Para extraer el texto de los PDFs del PJN instalá el extra `pdf` (u `ocr` para documentos
escaneados, que además requiere `tesseract` con idioma español y `poppler`):

```bash
uv tool install "ar-judicial[pdf] @ git+https://github.com/leandroecorrea/skills-abogados-ar"
```

> El extra `pdf` usa PyMuPDF, que tiene licencia AGPL. Es opcional: sin él, los PDFs se
> descargan igual y Claude puede leerlos directamente.

Probá que funcione (estos comandos usan catálogos incluidos en el paquete, no se conectan a ningún sistema):

```bash
ar-judicial mev juzgados --buscar "civil 1 avellaneda"
ar-judicial pjn jurisdicciones
```

### 2. Configurar tus credenciales

Creá el archivo `~/.config/ar-judicial/.env` con tus usuarios y claves (solo los sistemas que uses):

```bash
mkdir -p ~/.config/ar-judicial && chmod 700 ~/.config/ar-judicial
cat > ~/.config/ar-judicial/.env <<'EOF'
MEV_USUARIO=tu_usuario
MEV_CLAVE=tu_clave
PJN_USUARIO=20123456789   # CUIL sin guiones
PJN_CLAVE=tu_clave
EOF
chmod 600 ~/.config/ar-judicial/.env
```

También se pueden definir como variables de entorno. **No pegues tus claves en el chat con
Claude**: la herramienta las lee localmente y solo las envía al sistema judicial.

### 3. Instalar las skills

**Claude Code** (como plugin):

```
/plugin marketplace add leandroecorrea/skills-abogados-ar
/plugin install abogados-ar@skills-abogados-ar
```

O copiando la carpeta de la skill a mano:

```bash
git clone https://github.com/leandroecorrea/skills-abogados-ar
cp -r skills-abogados-ar/skills/mev-causas skills-abogados-ar/skills/pjn-expedientes ~/.claude/skills/
```

**Claude Desktop / claude.ai**: subí cada carpeta de `skills/` comprimida en ZIP desde
*Settings → Capabilities → Skills*. Las skills necesitan ejecutar `ar-judicial` con acceso a
`mev.scba.gov.ar` y `*.pjn.gov.ar`, por lo que funcionan mejor en Claude Code o en entornos
con acceso a tu máquina.

## Uso directo de la herramienta

```bash
ar-judicial mev departamentos
ar-judicial mev juzgados --departamento "la plata" --buscar trabajo
ar-judicial mev buscar --juzgado GAM2078 --numero 14107
ar-judicial mev buscar --juzgado GAM2078 --caratula "PEREZ C/ GOMEZ"
ar-judicial mev familia --departamento "san isidro"
ar-judicial mev causa --juzgado GAM2078 --causa 1281688
ar-judicial mev causa --juzgado GAM2078 --causa 1281688 --completa --salida ./causas
ar-judicial mev proveido --juzgado GAM2078 --codigo 1281688 --posicion 27606093

ar-judicial pjn jurisdicciones
ar-judicial pjn expedientes --buscar PEREZ
ar-judicial pjn causa --numero "CIV 008078/2025"
ar-judicial pjn causa --numero "CIV 008078/2025" --documentos --salida ./causas
ar-judicial pjn buscar --jurisdiccion CIV --numero 8078 --anio 2025
ar-judicial pjn buscar --jurisdiccion COM --parte "ACME SA" --abrir 0 --salida ./causas
```

Agregá `--json` antes del sistema (`ar-judicial --json mev ...`) para obtener JSON.

## Privacidad y uso responsable

- Todo corre en tu computadora: las credenciales y los expedientes no pasan por ningún
  servidor de terceros (más allá de lo que compartas con Claude en la conversación).
- La información de las causas está alcanzada por el secreto profesional. Elegí con cuidado
  dónde guardás los archivos descargados.
- Los sistemas judiciales son servicios públicos compartidos: evitá consultas masivas o en
  paralelo.
- Las sugerencias de plazos o pasos procesales que haga Claude son orientativas y deben
  verificarse siempre contra el expediente y la normativa aplicable.

## Desarrollo

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/pytest
```

Estructura:

```
src/ar_judicial/
├── mev/            # Cliente HTTP, parsers y modelos de la MEV
├── pjn/            # Login SSO, SCW, parsers, descarga de expedientes y PDFs del PJN
├── data/           # Catálogo de departamentos y juzgados de la MEV
├── catalog.py      # Búsqueda de juzgados por nombre
├── credentials.py  # Carga local de credenciales
├── render.py       # Salida en Markdown
└── cli.py          # Herramienta `ar-judicial`
skills/             # Skills de Claude (SKILL.md)
```

Las contribuciones son bienvenidas, especialmente reportes de cambios en los sistemas
judiciales que rompan los parsers.

## Licencia

[Apache 2.0](LICENSE). Ver [NOTICE](NOTICE).
