"""Google Gemini LLM provider with function-calling support."""

from __future__ import annotations

import json
import uuid
from typing import Any

import google.generativeai as genai

from llm.base import LLMProvider, LLMResponse, Message, ToolCall, ToolDefinition


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, temperature: float = 0.7) -> None:
        genai.configure(api_key=api_key)
        self._model_name = model
        self._temperature = temperature

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> LLMResponse:
        system_instruction = None
        conversation: list[Message] = []

        for msg in messages:
            if msg.role == "system":
                system_instruction = msg.content
            else:
                conversation.append(msg)

        gemini_tools = self._convert_tools(tools) if tools else None
        model = genai.GenerativeModel(
            self._model_name,
            system_instruction=system_instruction,
            tools=gemini_tools,
        )

        contents = self._build_contents(conversation)

        response = await model.generate_content_async(
            contents,
            generation_config=genai.GenerationConfig(temperature=self._temperature),
        )

        return self._parse_response(response)

    # ------------------------------------------------------------------
    # Internal conversions
    # ------------------------------------------------------------------

    def _convert_tools(self, tools: list[ToolDefinition]) -> list[dict]:
        """Convert OpenAI-format tool defs to Gemini function declarations."""
        declarations: list[dict[str, Any]] = []
        for tool in tools:
            func = tool.get("function", tool)
            decl: dict[str, Any] = {
                "name": func["name"],
                "description": func.get("description", ""),
            }
            if "parameters" in func:
                decl["parameters"] = self._convert_schema(func["parameters"])
            declarations.append(decl)
        return [{"function_declarations": declarations}]

    def _convert_schema(self, schema: dict) -> dict:
        """Recursively convert JSON Schema to Gemini Schema format."""
        result: dict[str, Any] = {}
        if "type" in schema:
            result["type_"] = schema["type"].upper()
        if "description" in schema:
            result["description"] = schema["description"]
        if "enum" in schema:
            result["enum"] = schema["enum"]
        if "properties" in schema:
            result["properties"] = {
                k: self._convert_schema(v) for k, v in schema["properties"].items()
            }
        if "required" in schema:
            result["required"] = schema["required"]
        if "items" in schema:
            result["items"] = self._convert_schema(schema["items"])
        return result

    def _build_contents(self, messages: list[Message]) -> list[dict]:
        """Convert unified messages to Gemini contents format."""
        contents: list[dict] = []

        for msg in messages:
            if msg.role == "user":
                contents.append({"role": "user", "parts": [{"text": msg.content or ""}]})

            elif msg.role == "assistant":
                parts: list[dict] = []
                if msg.content:
                    parts.append({"text": msg.content})
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        parts.append({
                            "function_call": {
                                "name": tc.name,
                                "args": tc.arguments,
                            }
                        })
                if parts:
                    contents.append({"role": "model", "parts": parts})

            elif msg.role == "tool":
                # Gemini expects function responses as user-role messages
                try:
                    response_data = json.loads(msg.content) if msg.content else {}
                except (json.JSONDecodeError, TypeError):
                    response_data = {"result": msg.content}

                contents.append({
                    "role": "user",
                    "parts": [{
                        "function_response": {
                            "name": msg.name or "unknown",
                            "response": response_data,
                        }
                    }],
                })

        return contents

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse Gemini response into our unified format."""
        tool_calls: list[ToolCall] = []
        text_parts: list[str] = []

        candidate = response.candidates[0]
        for part in candidate.content.parts:
            if hasattr(part, "function_call") and part.function_call:
                fc = part.function_call
                tool_calls.append(ToolCall(
                    id=f"call_{uuid.uuid4().hex[:12]}",
                    name=fc.name,
                    arguments=dict(fc.args) if fc.args else {},
                ))
            elif hasattr(part, "text") and part.text:
                text_parts.append(part.text)

        return LLMResponse(
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
        )
