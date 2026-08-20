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
curl -fsSL https://raw.githubusercontent.com/TU_USUARIO/filegraph/main/install.sh | bash
```

Esto clona el repo en `~/.local/share/filegraph`, instala dependencias, y configura OpenCode automáticamente.

### Instalación manual

```bash
git clone https://github.com/TU_USUARIO/filegraph.git
cd filegraph
pip install -e ".[dev]"
./scripts/setup-mcp.sh install
```

### Desinstalar

```bash
# Si usaste curl
bash ~/.local/share/filegraph/install.sh uninstall

# Si instalaste manualmente
./scripts/setup-mcp.sh uninstall
```

## Configurar en un cliente MCP

Agregar esta configuración a tu cliente MCP (OpenCode, Claude Desktop, etc.):

```json
{
  "mcpServers": {
    "filegraph": {
      "command": "python",
      "args": ["-m", "src.main"],
      "cwd": "/ruta/a/filegraph"
    }
  }
}
```

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
