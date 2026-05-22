"""Claude-powered red team agent with tool-use loop."""

from __future__ import annotations

import asyncio
import json

import anthropic

from caldera_client import CalderaClient
from tools import TOOLS, execute_tool

SYSTEM_PROMPT = """You are a red team agent with access to Caldera, a breach and attack simulation \
platform. Caldera has Atomic Red Team tests loaded natively via its atomic plugin, \
so all ART techniques are available through the standard Caldera abilities API.

Your job is to help security engineers test their defences by executing ATT&CK \
techniques on authorised target endpoints.

When a user asks you to run an attack:
1. Identify the most relevant ATT&CK technique(s) for their request
2. Use list_techniques to find what is available, then get_technique_detail \
for specifics
3. If the user has not specified a target, use list_techniques to show available \
agents and ask them to confirm before proceeding
4. Run the attack with run_attack and poll with get_operation_result
5. Report back clearly: technique ID and name, ability used, target host, \
whether execution succeeded (exit code), and the raw output
6. Summarise what a defender should have seen if detections were in place

Always be specific about technique IDs and ability names.
Never run attacks without a confirmed target agent paw.
If an operation is still running, poll get_operation_result again rather than \
giving up."""

MODEL = "claude-sonnet-4-20250514"


class RedAgent:
    """LLM agent that orchestrates Caldera via Claude tool calls."""

    def __init__(self, caldera: CalderaClient):
        """Initialise with a Caldera API client."""
        self.caldera = caldera
        self.client = anthropic.Anthropic()
        self.conversation_history: list[dict] = []

    async def chat(self, user_message: str) -> str:
        """Process a user message through the agent loop and return the final reply."""
        self.conversation_history.append(
            {"role": "user", "content": user_message}
        )

        messages = list(self.conversation_history)
        final_text = ""

        while True:
            response = await asyncio.to_thread(
                self.client.messages.create,
                model=MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

            assistant_content: list[dict] = []
            tool_uses = []

            for block in response.content:
                if block.type == "text":
                    final_text = block.text
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    tool_uses.append(block)
                    assistant_content.append(
                        {
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        }
                    )

            messages.append({"role": "assistant", "content": assistant_content})

            if response.stop_reason == "end_turn":
                break

            if response.stop_reason == "tool_use" and tool_uses:
                tool_results = []
                for tool_use in tool_uses:
                    result = await asyncio.to_thread(
                        execute_tool,
                        tool_use.name,
                        tool_use.input,
                        self.caldera,
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": json.dumps(result),
                        }
                    )
                messages.append({"role": "user", "content": tool_results})
                continue

            break

        self.conversation_history = messages
        return final_text
