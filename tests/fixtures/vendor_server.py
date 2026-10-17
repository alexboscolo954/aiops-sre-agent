"""A stand-in vendor MCP server, run as a subprocess over stdio. It imports nothing
from the project: the Hub must treat it as foreign. Each tool that runs appends its
name to $RAN_FILE, so a test in another process can see what ran."""

import os

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

mcp = FastMCP("vendor")
READ = ToolAnnotations(readOnlyHint=True)


def ran(name: str) -> str:
    if path := os.environ.get("RAN_FILE"):
        with open(path, "a") as f:
            f.write(name + "\n")
    return f"{name} ran"


@mcp.tool(annotations=READ)
def peek() -> str:
    """Claims read-only; the Hub says read: no approval."""
    return ran("peek")


@mcp.tool(annotations=READ)
def sneaky() -> str:
    """Claims read-only; the Hub says write: approval."""
    return ran("sneaky")


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
def honest() -> str:
    """Claims a write; the Hub says read: stricter wins, approval."""
    return ran("honest")


@mcp.tool
def unknown() -> str:
    """No annotation; the Hub says read: still a write."""
    return ran("unknown")


@mcp.tool(annotations=READ)
def unlisted() -> str:
    """Not on the Hub's list: never visible."""
    return ran("unlisted")


@mcp.tool(annotations=READ)
def environment() -> dict[str, str]:
    """What this process was given, and which process it is."""
    return {**os.environ, "PID": str(os.getpid())}


if __name__ == "__main__":
    mcp.run()
