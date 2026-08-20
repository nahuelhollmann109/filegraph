"""FastMCP server entry point for directory scanning tools."""

from __future__ import annotations

from fastmcp import FastMCP

from src.tools import (
    cache_status,
    find_duplicates,
    find_patterns,
    get_file_metadata,
    index_directory,
    scan_directory,
    search_by_type,
    sync_cache,
    unindex_directory,
)

mcp = FastMCP("filegraph")

# Scanning tools
mcp.tool()(scan_directory)
mcp.tool()(search_by_type)
mcp.tool()(get_file_metadata)
mcp.tool()(find_duplicates)
mcp.tool()(find_patterns)

# Cache management tools
mcp.tool()(index_directory)
mcp.tool()(sync_cache)
mcp.tool()(cache_status)
mcp.tool()(unindex_directory)


def main() -> None:
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
