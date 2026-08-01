# PSN Killer Database

Repositorio espejo y curado de catálogos TSV para PSN Killer Global.

La app usa este repositorio como fuente primaria para evitar pérdidas cuando una fuente pública devuelve un catálogo vacío, incompleto o temporalmente roto.

## Estructura

- `data/*.tsv`: catálogos descargables usados por la app.
- `data/pending/*.tsv`: catálogos pendientes de NoPayStation. Sirven para mostrar contenido ausente o incompleto en futuras versiones.
- `data/catalog_manifest.json`: conteos, checksums y fecha de la última actualización.
- `scripts/update_catalogs.py`: fusiona catálogos externos de forma incremental.

## Fuentes

El Action consulta:

1. NoPayStation: `https://nopaystation.com/tsv/<nombre.tsv>`
2. VitaWiki: `https://vitawiki.xyz/free/<nombre.tsv>`

Para PSX, VitaWiki usa `PS1_GAMES.tsv`; el script lo mapea automáticamente a `PSX_GAMES.tsv`.

## Política Incremental

El actualizador no reemplaza a ciegas. Lee el TSV actual, descarga fuentes externas y fusiona por clave estable:

- `Content ID`, si existe.
- Si no existe, `Title ID + Region + Name + Version`.

Si una fila nueva no existía, se añade. Si ya existía, solo se reemplaza cuando aporta más información útil, por ejemplo URL real, licencia, SHA256, tamaño o fecha de modificación.

Esto protege especialmente `PS3_UPDATES.tsv`, porque la fuente pública actual contiene muchas menos filas que el catálogo bueno preservado aquí.

## Ejecución Local

```bash
python3 scripts/update_catalogs.py
```
