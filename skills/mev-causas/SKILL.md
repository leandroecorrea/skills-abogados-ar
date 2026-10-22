---
name: mev-causas
description: Consulta causas de la Provincia de Buenos Aires en la MEV (Mesa de Entradas Virtual de la SCBA). Busca juzgados y sus códigos, encuentra causas por número o carátula, lista causas de Familia, descarga la lista de trámites o el expediente completo con el texto de cada proveído, y lee proveídos individuales. Usar cuando el usuario pida "buscá la causa", "bajame el expediente", "qué hay de nuevo en la causa", "leé el último proveído", "MEV", "SCBA", o mencione un juzgado bonaerense.
---

# MEV — causas de la SCBA

Toda la interacción con la MEV se hace con la herramienta `ar-judicial` (paquete Python de este repo).
No hagas scraping a mano: la herramienta ya maneja el login, la cookie de sesión, el departamento,
la paginación y la codificación Latin-1 de la MEV.

## 0. Preparación (una vez)

1. Verificá que la herramienta esté instalada: `ar-judicial --help`.
   Si no está:
   - con uv: `uv tool install git+https://github.com/leandroecorrea/skills-abogados-ar`
   - o con pip: `pip install git+https://github.com/leandroecorrea/skills-abogados-ar`
2. Credenciales: la herramienta lee `MEV_USUARIO` y `MEV_CLAVE` de variables de entorno o de
   `~/.config/ar-judicial/.env`. **Nunca le pidas al usuario que pegue la clave en el chat.**
   Si faltan (código de salida 2), indicale que cree el archivo él mismo:

   ```
   mkdir -p ~/.config/ar-judicial && chmod 700 ~/.config/ar-judicial
   # editar ~/.config/ar-judicial/.env con:
   MEV_USUARIO=su_usuario
   MEV_CLAVE=su_clave
   chmod 600 ~/.config/ar-judicial/.env
   ```

## 1. Identificar el juzgado (sin login)

La MEV necesita el **código del juzgado** (ej. `GAM2078`). El departamento se deduce solo.

```
ar-judicial mev juzgados --buscar "civil 1 avellaneda"
ar-judicial mev juzgados --departamento "la plata" --buscar trabajo
ar-judicial mev departamentos
```

Si hay varios resultados, mostrale la tabla al usuario y preguntá cuál es.
El catálogo cubre Civil y Comercial, Cámaras, Contencioso Administrativo, Trabajo, etc.
Las causas de **Familia** no se buscan por juzgado: usá `ar-judicial mev familia --departamento ...`.

## 2. Encontrar la causa

```
ar-judicial mev buscar --juzgado GAM2078 --numero 14107
ar-judicial mev buscar --juzgado GAM2078 --caratula "PEREZ C/ GOMEZ"
ar-judicial mev familia --departamento "san isidro"
```

La columna **nidCausa** es el identificador interno que necesitan los pasos siguientes
(no es el número de expediente).

## 3. Descargar la causa

- Lista de trámites (rápido): `ar-judicial mev causa --juzgado GAM2078 --causa 1281688`
- Expediente completo con el texto de cada proveído (una request por proveído, puede tardar minutos):
  `ar-judicial mev causa --juzgado GAM2078 --causa 1281688 --completa --salida ./causas`

Con `--salida` se guardan `expediente.md` (para leer) y `expediente.json` (datos estructurados)
en una carpeta por causa. Para causas largas usá siempre `--salida` y después leé el archivo,
en lugar de volcar todo a la terminal.

## 4. Leer un proveído puntual

Con el `nPosi` de la tabla de trámites:

```
ar-judicial mev proveido --juzgado GAM2078 --codigo 1281688 --posicion 27606093
```

## Análisis

Una vez descargado, vos hacés el análisis: resumen de la causa, partes, etapa procesal,
último movimiento relevante, plazos que podrían estar corriendo y próximos pasos sugeridos.
Señalá siempre que los plazos deben verificarse contra el expediente y el CPCC, y citá la fecha
y el título del proveído en el que te basás.

## Errores frecuentes

- `Error de MEV: Authentication failed`: credenciales incorrectas o usuario bloqueado en la MEV.
- `File not found or access denied`: el `nidCausa` no corresponde a ese juzgado, o el usuario
  no tiene acceso a la causa (p. ej., causas reservadas de Familia).
- Sin resultados en `buscar`: probá por carátula, o verificá el juzgado.

## Buenas prácticas

- No lances descargas masivas en paralelo: la MEV es un servicio público compartido.
- Los datos de las causas son confidenciales (secreto profesional): guardalos solo donde el
  usuario indique.
