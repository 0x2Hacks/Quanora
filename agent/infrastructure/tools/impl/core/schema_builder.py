"""Build OpenAI function schemas from Python tool signatures."""

from __future__ import annotations

import inspect
from types import NoneType, UnionType
from typing import Any, Callable, get_args, get_origin


def _json_type(annotation: Any) -> str:
    if annotation is inspect._empty:
        return "string"

    origin = get_origin(annotation)
    if origin in (list, tuple, set):
        return "array"
    if origin is dict:
        return "object"
    if origin in (UnionType,):
        args = [arg for arg in get_args(annotation) if arg is not NoneType]
        return _json_type(args[0]) if args else "string"
    if origin is not None and str(origin).endswith("Union"):
        args = [arg for arg in get_args(annotation) if arg is not NoneType]
        return _json_type(args[0]) if args else "string"

    mapping: dict[Any, str] = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }
    return mapping.get(annotation, "string")


def build_function_schema(
    *,
    name: str,
    func: Callable,
    description: str,
    param_descriptions: dict[str, str] | None = None,
) -> dict[str, Any]:
    signature = inspect.signature(func)
    properties: dict[str, dict[str, Any]] = {}
    required: list[str] = []
    param_descriptions = param_descriptions or {}

    for param_name, param in signature.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        item: dict[str, Any] = {"type": _json_type(param.annotation)}
        if param_name in param_descriptions:
            item["description"] = param_descriptions[param_name]
        if param.default is inspect._empty:
            required.append(param_name)
        else:
            item["default"] = param.default
        properties[param_name] = item

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def build_tool_schemas(
    tools: dict[str, Callable],
    meta: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    schemas: list[dict[str, Any]] = []
    for name, func in tools.items():
        tool_meta = meta.get(name)
        if not tool_meta:
            raise ValueError(f"Missing schema meta for tool: {name}")
        schemas.append(
            build_function_schema(
                name=name,
                func=func,
                description=tool_meta["description"],
                param_descriptions=tool_meta.get("param_descriptions"),
            )
        )
    return schemas
