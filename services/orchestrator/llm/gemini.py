"""Google Gemini LLM provider with function-calling support.

Uses the ``google-genai`` SDK (replacement for the deprecated
``google-generativeai`` package).
"""

from __future__ import annotations

import uuid
from typing import Any

from google import genai
from google.genai import types

from llm.base import LLMProvider, LLMResponse, Message, ToolCall, ToolDefinition


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, temperature: float = 0.7) -> None:
        self._client = genai.Client(api_key=api_key)
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

        config = types.GenerateContentConfig(
            temperature=self._temperature,
            system_instruction=system_instruction,
            tools=gemini_tools,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True,
            ),
        )

        contents = self._build_contents(conversation)

        response = await self._client.aio.models.generate_content(
            model=self._model_name,
            contents=contents,
            config=config,
        )

        return self._parse_response(response)

    # ------------------------------------------------------------------
    # Internal conversions
    # ------------------------------------------------------------------

    def _convert_tools(self, tools: list[ToolDefinition]) -> list[types.Tool]:
        """Convert OpenAI-format tool defs to Gemini function declarations."""
        declarations: list[types.FunctionDeclaration] = []
        for tool in tools:
            func = tool.get("function", tool)
            decl = types.FunctionDeclaration(
                name=func["name"],
                description=func.get("description", ""),
            )
            if "parameters" in func:
                decl.parameters_json_schema = func["parameters"]
            declarations.append(decl)
        return [types.Tool(function_declarations=declarations)]

    def _build_contents(self, messages: list[Message]) -> list[types.Content]:
        """Convert unified messages to Gemini contents format."""
        contents: list[types.Content] = []

        for msg in messages:
            if msg.role == "user":
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=msg.content or "")],
                ))

            elif msg.role == "assistant":
                parts: list[types.Part] = []
                if msg.content:
                    parts.append(types.Part.from_text(text=msg.content))
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        parts.append(types.Part.from_function_call(
                            name=tc.name,
                            args=tc.arguments,
                        ))
                if parts:
                    contents.append(types.Content(role="model", parts=parts))

            elif msg.role == "tool":
                # Parse tool result back to dict for Gemini
                try:
                    import json
                    response_data = json.loads(msg.content) if msg.content else {}
                except (json.JSONDecodeError, TypeError):
                    response_data = {"result": msg.content}

                contents.append(types.Content(
                    role="tool",
                    parts=[types.Part.from_function_response(
                        name=msg.name or "unknown",
                        response=response_data,
                    )],
                ))

        return contents

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse Gemini response into our unified format."""
        tool_calls: list[ToolCall] = []
        text_parts: list[str] = []

        candidate = response.candidates[0]
        if not candidate.content or not candidate.content.parts:
            return LLMResponse(content=None, tool_calls=[])
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
