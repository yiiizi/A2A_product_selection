"""
Filesystem MCP Server — FastMCP
端口 8202, streamable-http 传输

为 ReviewInsightAgent 提供:
  - read_csv: 读取 CSV 文件返回结构化数据
  - read_json: 读取 JSON 文件
  - list_dir: 列出目录文件
  - read_text: 读取文本文件

启动: python mcp_servers/filesystem_reader.py
"""

import csv
import json
import os
import sys
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp import FastMCP

logger = __import__("create_logger").get_logger("filesystem_mcp")
mcp = FastMCP("Filesystem Reader MCP", version="1.0.0")

# 允许访问的根目录 (安全沙箱)
ALLOWED_ROOTS = [
    str(Path(__file__).resolve().parent.parent),                  # backend/
    str(Path(__file__).resolve().parent.parent.parent / "data"),     # data/
]


def _safe_path(path_str: str) -> Path:
    p = Path(path_str).resolve()
    for root in ALLOWED_ROOTS:
        root_p = Path(root).resolve()
        try:
            p.relative_to(root_p)
            return p
        except ValueError:
            continue
    raise PermissionError(f"路径 {path_str} 不在允许的目录范围内: {ALLOWED_ROOTS}")


@mcp.tool()
def read_csv(file_path: str, max_rows: int = 100) -> dict:
    """读取 CSV 文件，返回前 N 行数据和列名。

    参数:
        file_path: CSV 文件路径 (相对于 backend/ 或 data/ 目录)
        max_rows: 最大返回行数 (默认100)
    """
    path = _safe_path(file_path)
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = []
        for i, row in enumerate(reader):
            if i >= max_rows:
                break
            rows.append(row)
        return {
            "file": str(path.name),
            "columns": reader.fieldnames or [],
            "total_read": len(rows),
            "rows": rows,
        }


@mcp.tool()
def read_json(file_path: str, key: str = "") -> dict:
    """读取 JSON 文件，返回解析后的数据。

    参数:
        file_path: JSON 文件路径
        key: 可选，提取 JSON 中的特定 key
    """
    path = _safe_path(file_path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if key and isinstance(data, dict):
        data = data.get(key, data)
    if isinstance(data, list) and len(data) > 100:
        data = data[:100]
    return {"file": str(path.name), "data": data}


@mcp.tool()
def list_dir(directory: str, pattern: str = "*") -> dict:
    """列出目录中的文件。

    参数:
        directory: 目录路径
        pattern: 文件名通配符 (如 *.csv)
    """
    import fnmatch
    path = _safe_path(directory)
    if not path.is_dir():
        path = path.parent
    files = []
    for f in sorted(path.iterdir()):
        if fnmatch.fnmatch(f.name, pattern):
            files.append({
                "name": f.name,
                "type": "dir" if f.is_dir() else "file",
                "size": f.stat().st_size if f.is_file() else 0,
            })
    return {"directory": str(path), "pattern": pattern, "files": files}


@mcp.tool()
def read_text(file_path: str, max_chars: int = 10000) -> dict:
    """读取文本文件内容 (txt, md, log 等)。

    参数:
        file_path: 文本文件路径
        max_chars: 最大读取字符数 (默认10000)
    """
    path = _safe_path(file_path)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read(max_chars + 1000)
    return {"file": str(path.name), "size": len(text), "text": text[:max_chars]}


if __name__ == "__main__":
    logger.info("Filesystem MCP Server starting on :8202 (streamable-http)")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8202, path="/mcp")
