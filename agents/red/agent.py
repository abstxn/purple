"""
Red Agent — LLM-powered agent using Ollama (llama3.1:8b) via OpenAI-compatible API.

The agent maintains conversation history across turns and supports multi-step
tool call chains: it keeps calling tools until the model returns a final
text response with no further tool calls.
"""

from __future__ import annotations

import asyncio
import json
import os

from openai import OpenAI

from caldera_client import CalderaClient
from tools import SYSTEM_PROMPT, TOOLS, execute_tool


class RedAgent:
    """LLM agent that orchestrates Caldera via Ollama tool calls."""

    def __init__(self, caldera: CalderaClient):
        """
        Initialise the red agent.

        Reads OLLAMA_BASE_URL and OLLAMA_MODEL from environment variables.
        Falls back to sensible defaults if not set.
        """
        self.caldera = caldera
        self.client = OpenAI(
            base_url=os.getenv(
                "OLLAMA_BASE_URL", "http://host.docker.internal:11434/v1"
            ),
            api_key="ollama",
        )
        self.model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        self.conversation_history: list[dict] = []

    def _build_messages(self) -> list[dict]:
        """Prepend system prompt to conversation history for each API call."""
        return [{"role": "system", "content": SYSTEM_PROMPT}] + self.conversation_history

    def _assistant_message_dict(self, message) -> dict:
        """Convert an OpenAI assistant message to a serialisable dict."""
        data = message.model_dump(exclude_none=True)
        if data.get("content") is None:
            data["content"] = ""
        return data

    async def chat(self, user_message: str) -> str:
        """
        Process a user message through the agent loop.

        Appends the user message to history, then enters a tool call loop:
        - If the model returns tool_calls, execute each tool and feed results back
        - Repeat until finish_reason is 'stop' (no more tool calls)
        - Return the final text response
        """
        self.conversation_history.append(
            {"role": "user", "content": user_message}
        )

        while True:
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model,
                messages=self._build_messages(),
                tools=TOOLS,
                temperature=0.0
            )

            choice = response.choices[0]

            if choice.finish_reason == "stop":
                final = choice.message.content or ""
                self.conversation_history.append(
                    {"role": "assistant", "content": final}
                )
                return final

            if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                self.conversation_history.append(
                    self._assistant_message_dict(choice.message)
                )

                for tc in choice.message.tool_calls:
                    try:
                        arguments = json.loads(tc.function.arguments)
                    except json.JSONDecodeError as exc:
                        result = {"error": f"Failed to parse tool arguments: {exc}"}
                    else:
                        result = await asyncio.to_thread(
                            execute_tool,
                            tc.function.name,
                            arguments,
                            self.caldera,
                        )

                    self.conversation_history.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(result),
                        }
                    )
                continue

            final = choice.message.content or ""
            self.conversation_history.append(
                {"role": "assistant", "content": final}
            )
            return final

    def reset(self) -> None:
        """Clear conversation history to start a fresh session."""
        self.conversation_history = []
