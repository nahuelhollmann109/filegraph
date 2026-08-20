"""FastMCP server entry point for directory scanning tools."""

from __future__ import annotations

from fastmcp import FastMCP

from src.tools import find_duplicates, find_patterns, get_file_metadata, scan_directory, search_by_type

mcp = FastMCP("filegraph")

mcp.tool()(scan_directory)
mcp.tool()(search_by_type)
mcp.tool()(get_file_metadata)
mcp.tool()(find_duplicates)
mcp.tool()(find_patterns)


def main() -> None:
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
