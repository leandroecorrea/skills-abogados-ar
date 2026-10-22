---
name: pjn-expedientes
description: Consulta expedientes del Poder Judicial de la Nación (PJN, sistema SCW) — fuero nacional y federal. Lista los expedientes del abogado (Relacionados, todos los perfiles), descarga un expediente con actuaciones, intervinientes y letrados, baja los PDFs de despachos y cédulas con su texto, y hace consultas públicas por número o por parte en cualquier cámara. Usar cuando el usuario mencione PJN, SCW, "mis expedientes", justicia nacional o federal, una cámara (CIV, COM, CNT, CSS, CAF, CCF, FLP, FSM...) o un número tipo "CIV 008078/2025".
---

# PJN — expedientes nacionales y federales (SCW)

Toda la interacción con el PJN se hace con la herramienta `ar-judicial` (paquete Python de este repo).
No hagas scraping a mano: la herramienta ya maneja el login SSO (Keycloak), los tokens, la sesión de
SCW, los ViewState de JSF y la paginación.

## 0. Preparación (una vez)

1. Verificá que la herramienta esté instalada: `ar-judicial --help`. Si no está:
   - `uv tool install "ar-judicial[pdf] @ git+https://github.com/leandroecorrea/skills-abogados-ar"`
   - o `pip install "ar-judicial[pdf] @ git+https://github.com/leandroecorrea/skills-abogados-ar"`

   El extra `[pdf]` permite extraer el texto de los PDFs. Para PDFs escaneados usá `[ocr]`,
   que además necesita `tesseract` (con idioma `spa`) y `poppler` instalados en el sistema.
2. Credenciales: `PJN_USUARIO` (el CUIL, sin guiones) y `PJN_CLAVE`, en variables de entorno o en
   `~/.config/ar-judicial/.env`. **Nunca le pidas al usuario que pegue la clave en el chat.**
   Si faltan (código de salida 2), indicale que agregue al archivo:

   ```
   PJN_USUARIO=20123456789
   PJN_CLAVE=su_clave
   ```

## 1. Mis expedientes

```
ar-judicial pjn expedientes
ar-judicial pjn expedientes --buscar "PEREZ"
```

Recorre todos los perfiles de Relacionados (letrado, autorizado, etc.) y todas las páginas.
Puede tardar si el abogado tiene muchos expedientes: ejecutalo una vez y trabajá sobre el resultado.

## 2. Descargar un expediente propio

Usá el **número exacto** de la tabla (y la dependencia si hay dos con el mismo número):

```
ar-judicial pjn causa --numero "CIV 008078/2025"
ar-judicial pjn causa --numero "CIV 008078/2025" --dependencia "JUZGADO CIVIL 88" --documentos --salida ./causas
```

- Sin `--documentos`: datos generales, intervinientes con sus letrados, y la tabla de actuaciones.
- Con `--documentos --salida DIR`: además descarga cada PDF a `DIR/<causa>/documentos/` y agrega
  su texto al `expediente.md`. Es una descarga por documento, de a uno: puede tardar varios minutos.

Si un PDF figura como "sin texto extraíble", es un escaneo: leé el PDF directamente desde la ruta
indicada (o sugerí instalar el extra `[ocr]`).

## 3. Consulta pública (cualquier expediente)

```
ar-judicial pjn jurisdicciones
ar-judicial pjn buscar --jurisdiccion CIV --numero 8078 --anio 2025
ar-judicial pjn buscar --jurisdiccion COM --parte "ACME SA"
ar-judicial pjn buscar --jurisdiccion CIV --numero 8078 --anio 2025 --abrir 0 --salida ./causas
```

`--abrir FILA` abre el resultado número FILA (columna `#`) y descarga el expediente igual que en el
paso 2. Con sesión iniciada, SCW no pide captcha. Si alguna vez la herramienta informa que se requiere
un captcha, no intentes resolverlo vos: pedile al usuario que haga esa consulta en
https://scw.pjn.gov.ar.

## Análisis

Una vez descargado, vos hacés el análisis: resumen, partes y letrados, situación actual, últimas
actuaciones relevantes (despachos firmados, cédulas), plazos que podrían estar corriendo y próximos
pasos. Para justicia nacional/federal aplica el CPCCN. Citá siempre la fecha y el tipo de la actuación
en la que te basás, y aclarale al usuario que los plazos deben verificarse contra el expediente.

## Errores frecuentes

- `Error de PJN: ...` al autenticar: CUIL o clave incorrectos, o la cuenta requiere cambiar la clave
  en el portal del PJN.
- `No se encontró el expediente ...`: no está en Relacionados con ese número exacto. Copiá el
  número de `pjn expedientes`, o usá `pjn buscar` para expedientes ajenos.

## Buenas prácticas

- No lances descargas en paralelo ni repitas `expedientes` innecesariamente: el PJN es un servicio
  público compartido.
- Los expedientes son confidenciales (secreto profesional): guardalos solo donde el usuario indique.
