# filegraph

Servidor MCP en Python 3.12 que escanea directorios y analiza la estructura de archivos para reorganización, limpieza y detección de patrones.

## Qué resuelve

Cuando trabajás con colecciones de archivos (logos, fotos, documentos, assets), necesitás responder preguntas como:

- **¿Qué hay en esta carpeta?** → `scan_directory` te da el árbol completo
- **¿Cuántos archivos .svg tengo?** → `search_by_type` filtra por extensión
- **¿Tengo archivos duplicados?** → `find_duplicates` los agrupa por hash
- **¿Hay patrones en los nombres?** → `find_patterns` detecta secuencias, prefijos y sufijos
- **¿Cuánto pesa cada archivo?** → `get_file_metadata` te da tamaño, permisos y fechas

filegraph se integra directamente con MCP (Model Context Protocol) para que agentes de IA puedan explorar y analizar directorios de forma autónoma, sin necesidad de navegar el sistema de archivos manualmente.

## Instalación

### Instalación rápida (recomendado)

```bash
curl -fsSL https://raw.githubusercontent.com/nahuelhollmann109/filegraph/main/install.sh | bash
```

### Qué hace el instalador

1. Muestra un **resumen de todo lo que va a hacer** antes de cambiar nada (con `--dry-run` lo podés ver sin ejecutar ninguna acción).
2. Clona o actualiza el repo en `~/.local/share/filegraph`.
3. Instala las dependencias Python con la primera estrategia que funcione: `uv` ya instalado → venv del sistema → `pip` del sistema → **bootstrap de uv en user-space** (descarga el binario fijado de su release oficial y verifica el checksum).
4. Detecta tu config de OpenCode (`$OPENCODE_CONFIG`, `opencode.json` o `opencode.jsonc`), crea un **backup una sola vez** (`<config>.filegraph.bak`) y registra el MCP con la ruta **absoluta** del intérprete con el que instaló las deps.
5. Corre un **smoke test** (el server tiene que arrancar) antes de anunciar éxito. Si algo falla, lo dice con la causa y la solución — nunca reporta éxito falso.

Todo pasa dentro de su directorio de instalación: **sin sudo, sin paquetes del sistema, sin tocar tus profiles de shell ni tu PATH**. El comando `uninstall` revierte todo lo creado.

### Requisitos

- `git`, `jq` y `python3` (≥ 3.12). Si falta alguno, el instalador imprime el comando exacto para tu distro (apt/dnf/yum/pacman/zypper/apk).
- No hace falta `pip` ni `python3-venv`: si el sistema no tiene ningún instalador usable, el instalador se trae su propio `uv`.

### Variables y opciones

| Variable / flag | Qué hace |
|-----------------|----------|
| `--dry-run` | Solo imprime el resumen de acciones; no cambia nada |
| `OPENCODE_CONFIG` | Ruta explícita a la config de OpenCode (si el archivo existe, tiene prioridad; si no, se detecta `.json`/`.jsonc`) |
| `FILEGRAPH_INSTALL_DIR` | Cambia el directorio de instalación (default: `~/.local/share/filegraph`) |
| `FILEGRAPH_PYTHON` / `--python <path>` | Intérprete que registra `setup-mcp.sh` (default: el que instaló las deps) |

### Instalación manual

```bash
git clone https://github.com/nahuelhollmann109/filegraph.git
cd filegraph
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
FILEGRAPH_PYTHON="$PWD/.venv/bin/python" ./scripts/setup-mcp.sh install
```

### Desinstalar

```bash
# Si usaste curl
bash ~/.local/share/filegraph/install.sh uninstall

# Si instalaste manualmente
./scripts/setup-mcp.sh uninstall
```

Elimina el server de OpenCode y borra todo su directorio de instalación (repo, venv y uv). El backup `<config>.filegraph.bak` se conserva a propósito.

## Configurar en un cliente MCP

Agregar esta configuración a tu cliente MCP (Claude Desktop, etc.). Usá siempre la ruta **absoluta** del intérprete — los clientes MCP no heredan tu PATH ni un venv activo:

```json
{
  "mcpServers": {
    "filegraph": {
      "command": "/ruta/a/filegraph/.venv/bin/python",
      "args": ["-m", "src.main"],
      "cwd": "/ruta/a/filegraph"
    }
  }
}
```

Si instalaste con curl, la ruta exacta aparece al final del instalador.

## Tools de escaneo

### `scan_directory`

Escanea un directorio y devuelve su jerarquía como árbol JSON.

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `path` | str | ✅ | Ruta del directorio a escanear |
| `max_depth` | int | ❌ | Profundidad máxima (None = sin límite) |
| `exclude_dirs` | list[str] | ❌ | Directorios a excluir |
| `include_excluded` | bool | ❌ | Incluir directorios excluidos por defecto |

**Ejemplo:**

```json
{
  "tree": {
    "type": "directory",
    "name": "Logos-html",
    "children": [
      {"type": "file", "name": "logo.svg", "size": 68936},
      {"type": "file", "name": "icon.png", "size": 47672}
    ]
  },
  "warnings": []
}
```

### `search_by_type`

Busca archivos por extensión bajo una ruta específica.

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `path` | str | ✅ | Directorio raíz para buscar |
| `file_type` | str | ✅ | Extensión a filtrar (ej: `jpg`, `png`, `pdf`) |
| `exclude_dirs` | list[str] | ❌ | Directorios a excluir |
| `include_excluded` | bool | ❌ | Incluir directorios excluidos por defecto |

**Ejemplo:**

```json
{
  "results": [
    {"name": "photo.jpg", "path": "/home/user/fotos/photo.jpg", "size": 1234567}
  ]
}
```

### `find_duplicates`

Encuentra archivos duplicados agrupados por hash (SHA256 por defecto).

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `path` | str | ✅ | Directorio a analizar |
| `hash_algo` | str | ❌ | Algoritmo: sha256, md5 (default: sha256) |
| `min_size` | int | ❌ | Tamaño mínimo en bytes |

**Ejemplo:**

```json
{
  "duplicates": [
    {
      "hash": "abc123...",
      "size": 123456,
      "files": [
        "/home/user/fotos/photo1.jpg",
        "/home/user/fotos/backup/photo1.jpg"
      ]
    }
  ]
}
```

### `find_patterns`

Detecta patrones en nombres de archivo (secuencias, prefijos, sufijos, fechas).

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `path` | str | ✅ | Directorio a analizar |
| `strategy` | str | ❌ | auto, prefix, suffix, sequence, date |
| `min_group_size` | int | ❌ | Tamaño mínimo de grupo (default: 3) |

**Ejemplo:**

```json
{
  "patterns": [
    {
      "type": "sequence",
      "pattern": "menu{1}",
      "files": ["menu1.svg", "menu2.svg", "menu3.svg"]
    }
  ]
}
```

### `get_file_metadata`

Obtiene metadata detallada de un archivo específico.

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `path` | str | ✅ | Ruta del archivo |

**Ejemplo:**

```json
{
  "name": "documento.pdf",
  "size": 45678,
  "modified": "2026-08-16T10:30:00Z",
  "created": "2026-08-16T10:30:00Z",
  "permissions": "rw-r--r--",
  "is_symlink": false
}
```

## Tools de caché

filegraph almacena resultados de escaneo en SQLite para que las búsquedas subsiguientes sean instantáneas.

### `index_directory`

Indexa un directorio y cachea sus resultados.

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `path` | str | ✅ | Directorio a indexar |

### `sync_cache`

Sincroniza el caché — refresca archivos modificados, agrega nuevos.

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `path` | str | ✅ | Directorio a sincronizar |

### `cache_status`

Muestra estadísticas del caché (entradas, archivos totales, tamaño).

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `path` | str | ❌ | Directorio a consultar (omitir = global) |

### `unindex_directory`

Elimina un directorio del caché.

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `path` | str | ✅ | Directorio a eliminar del caché |

## Comportamiento

- **Symlinks**: No se siguen por defecto (seguridad)
- **Permisos**: Si un directorio no tiene permisos de lectura, retorna resultados parciales con warning
- **Unicode**: Los nombres de archivos Unicode se preservan exactamente
- **Exclusiones por defecto**: `.git`, `node_modules`, `__pycache__`, `.venv` se excluyen automáticamente
- **Personalización**: Usa `--no-exclude` en CLI o `include_excluded=True` en tools para incluir directorios excluidos

## CLI

El proyecto incluye un comando `filegraph` que se instala automáticamente:

```bash
# Ver ayuda
filegraph --help

# Comandos disponibles
filegraph scan <directorio>                    # Escanea y muestra árbol
filegraph search <directorio> <extensión>     # Busca por extensión
filegraph find-duplicates <directorio>        # Encuentra duplicados
filegraph find-patterns <directorio>          # Detecta patrones
filegraph index <directorio>                  # Indexa y cachea
filegraph sync <directorio>                   # Sincroniza caché
filegraph cache-status [directorio]           # Muestra stats del caché
```

### Ejemplos CLI

```bash
# Escaneo en formato JSON
filegraph scan /ruta/a/proyecto --format json

# Escaneo con profundidad limitada
filegraph scan /ruta/a/proyecto --format tree --depth 3

# Buscar duplicados con hash MD5 y tamaño mínimo
filegraph find-duplicates /ruta/a/proyecto --algo md5 --min-size 1000

# Buscar archivos .jpg incluyendo directorios excluidos
filegraph search /ruta/a/proyecto jpg --no-exclude

# Detectar solo secuencias con grupo mínimo de 5
filegraph find-patterns /ruta/a/proyecto --strategy sequence --min-group 5

# Indexar un directorio para búsquedas rápidas
filegraph index /ruta/a/proyecto

# Ver estado del caché
filegraph cache-status /ruta/a/proyecto
```

## Testing

```bash
python -m pytest tests/ -v
```

## Estructura del proyecto

```
filegraph/
├── pyproject.toml
├── .github/workflows/ci.yml
├── src/
│   ├── __init__.py
│   ├── main.py           # Entry point del server MCP
│   ├── tools.py          # Definición de las tools MCP
│   ├── scanner.py        # Lógica core de escaneo
│   ├── cache.py          # SQLite cache manager
│   └── cli.py            # Comando CLI filegraph
└── tests/
    ├── __init__.py
    ├── test_scanner.py
    ├── test_tools_cache.py
    ├── test_cli.py
    └── test_cli_cache.py
```
