"""Servidor MCP real (stdio, JSON-RPC 2.0) para el agente generador-prp.

Implementa el contrato de `workspaces/generador-prp/package/tools.json` sobre el sistema de archivos:
    listar_fuentes()                     -> fuentes de ./fuentes (nombre y fecha de modificación)
    leer_fuente(nombre)                  -> texto completo de una fuente
    guardar_prp(nombre_archivo, contenido) -> escribe en ./prp; falla si el archivo ya existe

Sin dependencias. Rutas por defecto relativas a la raíz del repo (carpeta padre de este archivo);
se pueden cambiar con --fuentes y --salida. Lo registra .mcp.json con el nombre de servidor `trilogi`,
que es el que espera el frontmatter del agente (mcp__trilogi__<tool>).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_EXTENSIONS = {".txt", ".md", ".eml", ".html", ".htm", ".csv", ".json"}

TOOLS = [
    {
        "name": "listar_fuentes",
        "description": "Devuelve la lista de fuentes disponibles del cliente (emails, notas de reunión, briefings) con nombre y fecha.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "leer_fuente",
        "description": "Devuelve el texto completo de una fuente por su nombre.",
        "inputSchema": {"type": "object", "properties": {"nombre": {"type": "string"}}, "required": ["nombre"]},
    },
    {
        "name": "guardar_prp",
        "description": "Guarda el PRP generado (Markdown) con el nombre de archivo indicado. Falla si el archivo ya existe.",
        "inputSchema": {
            "type": "object",
            "properties": {"nombre_archivo": {"type": "string"}, "contenido": {"type": "string"}},
            "required": ["nombre_archivo", "contenido"],
        },
    },
]


class ToolError(Exception):
    pass


def _safe_name(name: str) -> str:
    name = (name or "").strip()
    if not name or Path(name).name != name or name in (".", ".."):
        raise ToolError(f"nombre de archivo no válido: {name!r}")
    return name


def listar_fuentes(sources: Path) -> dict[str, Any]:
    if not sources.is_dir():
        raise ToolError(f"no existe el directorio de fuentes: {sources}")
    items = []
    for f in sorted(sources.iterdir()):
        if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in SOURCE_EXTENSIONS:
            items.append({
                "nombre": f.name,
                "fecha": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d"),
                "bytes": f.stat().st_size,
            })
    return {"fuentes": items, "total": len(items)}


def leer_fuente(sources: Path, nombre: str) -> dict[str, Any]:
    f = sources / _safe_name(nombre)
    if not f.is_file():
        raise ToolError(f"no existe la fuente {nombre!r}")
    return {"nombre": f.name, "contenido": f.read_text(encoding="utf-8", errors="replace")}


def guardar_prp(out_dir: Path, nombre_archivo: str, contenido: str) -> dict[str, Any]:
    f = out_dir / _safe_name(nombre_archivo)
    if not isinstance(contenido, str) or not contenido.strip():
        raise ToolError("el contenido está vacío")
    out_dir.mkdir(parents=True, exist_ok=True)
    if f.exists():
        raise ToolError(f"el archivo ya existe: {f.name}. Usa otro nombre o una versión nueva (_vN+1)")
    f.write_text(contenido, encoding="utf-8")
    return {"ok": True, "ruta": str(f), "bytes": f.stat().st_size}


def call(sources: Path, out_dir: Path, name: str, args: dict[str, Any]) -> Any:
    if name == "listar_fuentes":
        return listar_fuentes(sources)
    if name == "leer_fuente":
        return leer_fuente(sources, args.get("nombre", ""))
    if name == "guardar_prp":
        return guardar_prp(out_dir, args.get("nombre_archivo", ""), args.get("contenido", ""))
    raise ToolError(f"tool desconocida: {name}")


def serve(sources: Path, out_dir: Path) -> None:
    def send(obj: dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = req.get("method")
        rid = req.get("id")

        if method == "initialize":
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": req.get("params", {}).get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "trilogi", "version": "0.1.0"},
            }})
        elif method == "notifications/initialized":
            pass
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": rid, "result": {}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = req.get("params", {}) or {}
            name = params.get("name", "")
            args = params.get("arguments", {}) or {}
            try:
                out, is_err = call(sources, out_dir, name, args), False
            except ToolError as e:
                out, is_err = {"ok": False, "error": str(e)}, True
            except Exception as e:  # noqa: BLE001 - nunca tumbar el servidor por una llamada
                out, is_err = {"ok": False, "error": f"{type(e).__name__}: {e}"}, True
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
                "isError": is_err,
            }})
        elif rid is not None:
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"método no soportado: {method}"}})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fuentes", default=str(ROOT / "fuentes"), help="directorio con las comunicaciones del cliente")
    ap.add_argument("--salida", default=str(ROOT / "prp"), help="directorio donde se guardan los PRP")
    a = ap.parse_args()
    serve(Path(a.fuentes).resolve(), Path(a.salida).resolve())


if __name__ == "__main__":
    main()
