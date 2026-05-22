# Task: Transition Red Agent from Anthropic to Ollama

## Goal

Replace the Anthropic SDK in the red agent with Ollama running locally via the
OpenAI-compatible API. Ollama runs on the host machine (not in Docker) and is
accessed from the red-agent container via `host.docker.internal`.

The model to use is `llama3.1:8b` — chosen for its reliable tool calling
support, Apple Silicon performance via Metal acceleration, and sufficient
ATT&CK domain knowledge for structured API orchestration tasks.

---

## Prerequisites (do not implement — for context only)

Ollama is already installed and running on the host via:
```bash
brew services start ollama
ollama pull llama3.1:8b
```

---

## Changes Required

### 1. `agents/red/requirements.txt`

Remove `anthropic`. Add `openai`:

```
fastapi
uvicorn
httpx
openai
pyyaml
pydantic
```

### 2. `.env.example`

Remove `ANTHROPIC_API_KEY`. Add Ollama config:

```
CALDERA_URL=http://caldera:8888
CALDERA_API_KEY=

OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
OLLAMA_MODEL=llama3.1:8b
```

Remove `ANTHROPIC_API_KEY` from the actual `.env` file as well if it exists.

### 3. `agents/red/agent.py`

Full rewrite of the agent to use the OpenAI SDK pointed at Ollama.

```python
"""
Red Agent — LLM-powered agent using Ollama (llama3.1:8b) via OpenAI-compatible API.

The agent maintains conversation history across turns and supports multi-step
tool call chains: it keeps calling tools until the model returns a final
text response with no further tool calls.
"""

import json
import os
from openai import OpenAI
from .caldera_client import CalderaClient
from .tools import TOOLS, SYSTEM_PROMPT, execute_tool


class RedAgent:
    def __init__(self, caldera: CalderaClient):
        """
        Initialise the red agent.

        Reads OLLAMA_BASE_URL and OLLAMA_MODEL from environment variables.
        Falls back to sensible defaults if not set.
        """
        self.caldera = caldera
        self.client = OpenAI(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434/v1"),
            api_key="ollama",   # Required by SDK but ignored by Ollama
        )
        self.model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        self.conversation_history: list[dict] = []

    def _build_messages(self) -> list[dict]:
        """Prepend system prompt to conversation history for each API call."""
        return [{"role": "system", "content": SYSTEM_PROMPT}] + self.conversation_history

    async def chat(self, user_message: str) -> str:
        """
        Process a user message through the agent loop.

        Appends the user message to history, then enters a tool call loop:
        - If the model returns tool_calls, execute each tool and feed results back
        - Repeat until finish_reason is 'stop' (no more tool calls)
        - Return the final text response

        All messages (user, assistant, tool results) are appended to
        conversation_history so context is maintained across turns.
        """
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })

        while True:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self._build_messages(),
                tools=TOOLS,
            )

            choice = response.choices[0]

            # No tool calls — final response
            if choice.finish_reason == "stop":
                final = choice.message.content
                self.conversation_history.append({
                    "role": "assistant",
                    "content": final
                })
                return final

            # Tool calls — execute and feed results back
            if choice.finish_reason == "tool_calls":
                # Append the assistant's tool call message to history
                self.conversation_history.append(choice.message)

                for tc in choice.message.tool_calls:
                    try:
                        arguments = json.loads(tc.function.arguments)
                    except json.JSONDecodeError as e:
                        result = {"error": f"Failed to parse tool arguments: {e}"}
                    else:
                        result = execute_tool(
                            tool_name=tc.function.name,
                            tool_input=arguments,
                            caldera=self.caldera
                        )

                    self.conversation_history.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result)
                    })

            # Unexpected finish reason — treat as final
            else:
                final = choice.message.content or ""
                self.conversation_history.append({
                    "role": "assistant",
                    "content": final
                })
                return final

    def reset(self):
        """Clear conversation history to start a fresh session."""
        self.conversation_history = []
```

### 4. `agents/red/tools.py`

The tool schemas themselves do not change — the OpenAI tool calling format is
identical to what was already defined. However, move `SYSTEM_PROMPT` into this
file so it is importable by `agent.py`:

```python
SYSTEM_PROMPT = """You are a red team agent with access to Caldera, a breach \
and attack simulation platform. Caldera has Atomic Red Team tests loaded \
natively via its atomic plugin, so all ART techniques are available through \
the standard Caldera abilities API.

Your job is to help security engineers test their defences by executing ATT&CK \
techniques on authorised target endpoints.

When a user asks you to run an attack:
1. Identify the most relevant ATT&CK technique(s) for their request
2. Use list_techniques to find what is available, then get_technique_detail \
for specifics
3. If the user has not specified a target, call list_techniques to show \
available agents and ask them to confirm before proceeding
4. Run the attack with run_attack and poll with get_operation_result
5. Report back clearly: technique ID and name, ability used, target host, \
whether execution succeeded (exit code), and the raw output
6. Summarise what a defender should have seen if detections were in place

Always be specific about technique IDs and ability names.
Never run attacks without a confirmed target agent paw.
If an operation is still running, poll get_operation_result again rather \
than giving up."""
```

Ensure `TOOLS` is still defined in this file and exported. No changes to the
tool schemas themselves.

### 5. `agents/red/main.py`

Two small changes:

- Remove any import or reference to `anthropic`
- Add a `POST /reset` endpoint that calls `agent.reset()` to clear conversation
  history, useful during development:

```python
@app.post("/reset")
async def reset_conversation():
    """Clear the agent's conversation history."""
    agent.reset()
    return {"status": "conversation reset"}
```

### 6. `agents/red/Dockerfile`

No changes needed — `openai` will be installed via `requirements.txt`.

---

## Validation Steps

After making these changes, verify the following:

**1. Container builds without errors:**
```bash
docker-compose build red-agent
```

**2. Health check passes:**
```bash
curl http://localhost:8001/health
```
Expected: `{"status": "ok", "caldera_reachable": true}`

**3. Ollama is reachable from inside the container:**
```bash
docker exec <red-agent-container> curl http://host.docker.internal:11434/api/tags
```
Expected: JSON response listing available models including `llama3.1:8b`

**4. Basic chat works:**
```bash
curl -X POST http://localhost:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What ATT&CK techniques are available for the execution tactic?"}'
```
Expected: A text response listing techniques — the model should call
`list_techniques` internally and summarise the results.

**5. Conversation reset works:**
```bash
curl -X POST http://localhost:8001/reset
```
Expected: `{"status": "conversation reset"}`

---

## Notes

- `api_key="ollama"` is a placeholder required by the OpenAI SDK — Ollama
  ignores it entirely
- `host.docker.internal` is Docker Desktop's magic hostname that resolves to
  the host machine from inside a container. This works on Mac and Windows.
  On Linux it may need to be added manually to `docker-compose.yml`:
  ```yaml
  extra_hosts:
    - "host.docker.internal:host-gateway"
  ```
- If `llama3.1:8b` produces malformed tool call JSON, `qwen2.5:7b` is the
  recommended fallback — change `OLLAMA_MODEL` in `.env` to switch
- The `openai` SDK is used here purely as an HTTP client for the
  OpenAI-compatible API — no OpenAI account or API key is involved