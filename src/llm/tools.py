"""Typed tool registry for tool-calling agents.

Each :class:`Tool` pairs a Pydantic input schema with a handler. The registry
renders the OpenAI ``tools`` payload and dispatches a call: it validates the
model's arguments against the schema (invalid args return a structured error the
model can correct, rather than raising) and returns a JSON-serializable result.
"""

import json
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Tool:
    name: str
    description: str
    input_schema: type[BaseModel]
    handler: Callable[[BaseModel], Any]

    def openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema.model_json_schema(),
            },
        }


class ToolRegistry:
    def __init__(self, tools: list[Tool]):
        self._tools = {t.name: t for t in tools}

    def openai_tools(self) -> list[dict]:
        return [t.openai_schema() for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)

    def dispatch(self, name: str, arguments: str) -> dict:
        """Run a tool call. Returns ``{"ok": True, "result": ...}`` or, on bad
        input, ``{"ok": False, "error": ...}`` so the model can retry."""
        tool = self._tools.get(name)
        if tool is None:
            return {"ok": False, "error": f"unknown tool '{name}'"}

        try:
            raw = json.loads(arguments or "{}")
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"arguments were not valid JSON: {exc}"}

        try:
            args = tool.input_schema.model_validate(raw)
        except ValidationError as exc:
            return {"ok": False, "error": f"invalid arguments: {exc}"}

        try:
            result = tool.handler(args)
        except Exception as exc:  # a failing data source degrades to an error result
            logger.warning("Tool '%s' failed: %s", name, exc)
            return {"ok": False, "error": f"tool execution failed: {exc}"}

        return {"ok": True, "result": result}
