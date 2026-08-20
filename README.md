# FileGraph — MCP Directory Scanner

Servidor MCP en Python 3.12 que escanea directorios y devuelve la jerarquía de archivos/carpetas para reorganización.

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

## Uso

### Comando CLI

El proyecto incluye un comando `filegraph` que se instala automáticamente:

```bash
# Instalar el comando
pip install -e ".[dev]"

# Ver ayuda
filegraph --help
filegraph scan --help
filegraph find-duplicates --help
filegraph search --help
filegraph find-patterns --help
```

#### Comandos disponibles

- **`filegraph scan <directorio>`**: Escanea un directorio y muestra su estructura
  - `--format json|tree`: Formato de salida (por defecto: tree)
  - `--no-exclude`: Incluir directorios excluidos por defecto
  - `--depth N`: Profundidad máxima de escaneo

- **`filegraph find-duplicates <directorio>`**: Encuentra archivos duplicados por hash
  - `--format json|tree`: Formato de salida (por defecto: tree)
  - `--algo SHA256|MD5`: Algoritmo de hash (por defecto: sha256)
  - `--min-size N`: Tamaño mínimo en bytes para considerar

- **`filegraph search <directorio> <extensión>`**: Busca archivos por extensión
  - `--format json|tree`: Formato de salida (por defecto: tree)
  - `--no-exclude`: Incluir directorios excluidos

- **`filegraph find-patterns <directorio>`**: Detecta patrones en nombres de archivo
  - `--format json|tree`: Formato de salida (por defecto: tree)
  - `--strategy auto|prefix|suffix|sequence|date`: Estrategia de detección
  - `--min-group N`: Tamaño mínimo de grupo (por defecto: 3)

#### Exclusiones por defecto

Los siguientes directorios se excluyen automáticamente:
- `.git` — repositorios git
- `node_modules` — dependencias Node.js
- `__pycache__` — archivos compilados Python
- `.venv` — entornos virtuales Python

Para incluir estos directorios, usa `--no-exclude`.

#### Ejemplos

```bash
# Escaneo en formato JSON
filegraph scan /ruta/a/proyecto --format json

# Escaneo en formato árbol con profundidad limitada
filegraph scan /ruta/a/proyecto --format tree --depth 3

# Buscar duplicados excluyendo directorios por defecto
filegraph find-duplicates /ruta/a/proyecto

# Buscar duplicados con hash MD5 y tamaño mínimo
filegraph find-duplicates /ruta/a/proyecto --algo md5 --min-size 1000

# Buscar archivos .jpg sin exclusiones
filegraph search /ruta/a/proyecto jpg --no-exclude

# Detectar patrones con estrategia automática
filegraph find-patterns /ruta/a/proyecto

# Detectar solo secuencias con grupo mínimo de 5
filegraph find-patterns /ruta/a/proyecto --strategy sequence --min-group 5
```

### Ejecutar el server MCP

```bash
python -m src.main
```

### Configurar en un cliente MCP

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

## Tools disponibles

### `scan_directory`

Escanea un directorio y devuelve su jerarquía como árbol JSON.

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `path` | str | ✅ | Ruta del directorio a escanear |
| `max_depth` | int | ❌ | Profundidad máxima de traverse (None = sin límite) |
| `exclude_dirs` | list[str] | ❌ | Directorios a excluir |
| `include_excluded` | bool | ❌ | Incluir directorios excluidos por defecto |

**Ejemplo de respuesta:**

```json
{
  "tree": {
    "type": "directory",
    "name": "fotos",
    "children": [
      {
        "type": "file",
        "name": "vacation.jpg",
        "path": "/home/user/fotos/vacation.jpg",
        "size": 2456789
      }
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

**Ejemplo de respuesta:**

```json
{
  "results": [
    {
      "name": "photo.jpg",
      "path": "/home/user/fotos/photo.jpg",
      "size": 1234567
    }
  ]
}
```

### `find_duplicates`

Encuentra archivos duplicados agrupados por hash.

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `path` | str | ✅ | Directorio a analizar |
| `hash_algo` | str | ❌ | Algoritmo de hash (por defecto: sha256) |
| `min_size` | int | ❌ | Tamaño mínimo en bytes |

**Ejemplo de respuesta:**

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

Detecta patrones en nombres de archivo (prefijos, sufijos, secuencias, fechas).

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `path` | str | ✅ | Directorio a analizar |
| `strategy` | str | ❌ | Estrategia: auto, prefix, suffix, sequence, date |
| `min_group_size` | int | ❌ | Tamaño mínimo de grupo (por defecto: 3) |

**Ejemplo de respuesta:**

```json
{
  "patterns": [
    {
      "type": "sequence",
      "pattern": "photo_{number}.jpg",
      "files": [
        "/home/user/fotos/photo_001.jpg",
        "/home/user/fotos/photo_002.jpg",
        "/home/user/fotos/photo_003.jpg"
      ]
    }
  ]
}
```

### `get_file_metadata`

Obtiene metadata detallada de un archivo específico.

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `path` | str | ✅ | Ruta del archivo |

**Ejemplo de respuesta:**

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

## Comportamiento

- **Symlinks**: No se siguen por defecto (seguridad)
- **Permisos**: Si un directorio no tiene permisos de lectura, retorna resultados parciales con warning
- **Unicode**: Los nombres de archivos Unicode se preservan exactamente
- **Path requerido**: Todas las tools requieren `path` — cada operación solo trabaja sobre la ruta indicada
- **Exclusiones por defecto**: `.git`, `node_modules`, `__pycache__`, `.venv` se excluyen automáticamente
- **Personalización**: Usa `--no-exclude` en CLI o `include_excluded=True` en tools para incluir directorios excluidos

## Testing

```bash
python -m pytest tests/ -v
```

## Estructura del proyecto

```
filegraph/
├── pyproject.toml        # Metadata y dependencias
├── .github/
│   └── workflows/
│       └── ci.yml        # GitHub Actions CI
├── src/
│   ├── __init__.py
│   ├── main.py           # Entry point del server MCP
│   ├── tools.py          # Definición de las tools MCP
│   ├── scanner.py        # Lógica core de escaneo
│   └── cli.py            # Comando CLI filegraph
└── tests/
    ├── __init__.py
    ├── test_scanner.py   # Unit tests del scanner
    └── test_cli.py       # Tests del CLI
```
