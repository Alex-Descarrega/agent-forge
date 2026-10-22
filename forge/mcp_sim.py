"""Servidor MCP mínimo (stdio, JSON-RPC 2.0) que simula las herramientas del contrato.

Lo lanza `claude -p --mcp-config ...` para cada caso. Lee un archivo JSON con:
    {"tools": [...contrato...], "tool_responses": {...}, "trace_log": "ruta"}
y registra cada llamada en trace_log (una línea JSON por llamada), que el runner lee después.

Sin dependencias: implementa solo initialize / tools/list / tools/call / ping.
Uso: python -m forge.mcp_sim <case_file.json>
"""

from __future__ import annotations

import json
import sys
from typing import Any


def _schema(input_schema: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    props = {}
    for k, v in (input_schema or {}).items():
        props[k] = v if isinstance(v, dict) else {"type": v if v in ("string", "number", "integer", "boolean") else "string"}
    out: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        out["required"] = [r for r in required if r in props]
    return out


def _resolve(tool_responses: dict[str, Any], name: str, inp: dict[str, Any]) -> tuple[Any, bool]:
    """Misma lógica que forge.schemas.resolve_tool_response, duplicada para no depender del paquete."""
    if name not in tool_responses:
        return {"ok": True, "simulated": True, "received": inp}, False
    spec = tool_responses[name]
    if isinstance(spec, list) and spec and all(isinstance(x, dict) and "response" in x for x in spec):
        for rule in spec:
            match = rule.get("match") or {}
            if all(str(inp.get(k, "")).strip().lower() == str(v).strip().lower() for k, v in match.items()):
                return rule["response"], bool(rule.get("is_error", False))
        return {"ok": False, "simulated": True, "error": "sin respuesta simulada para este input", "received": inp}, True
    return spec, False


def main(case_file: str) -> None:
    cfg = json.load(open(case_file, encoding="utf-8"))
    tools = cfg["tools"]
    responses = cfg.get("tool_responses", {})
    log_path = cfg["trace_log"]

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
                "serverInfo": {"name": "forge", "version": "0.1.0"},
            }})
        elif method == "notifications/initialized":
            pass
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": rid, "result": {}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": rid, "result": {"tools": [
                {"name": t["name"], "description": t.get("description", ""), "inputSchema": _schema(t.get("input_schema", {}), t.get("required"))}
                for t in tools
            ]}})
        elif method == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {}) or {}
            out, is_err = _resolve(responses, name, args)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"name": name, "input": args, "output": out, "is_error": is_err}, ensure_ascii=False) + "\n")
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
                "isError": is_err,
            }})
        elif rid is not None:
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"método no soportado: {method}"}})


if __name__ == "__main__":
    main(sys.argv[1])
