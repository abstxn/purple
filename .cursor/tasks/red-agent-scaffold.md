# Task: Scaffold Red Agent Monorepo (Iteration 1)

## Goal
Build the foundational monorepo structure for an autonomous security validation 
platform. This iteration focuses exclusively on the **red agent** — an 
LLM-powered service that integrates with Caldera (BAS) and Atomic Red Team (ART)
to execute ATT&CK techniques on a target Windows endpoint.

---

## Monorepo Structure to Create

```
/
├── docker-compose.yml
├── .env.example
├── .gitmodules
├── .gitignore
│
├── agents/
│   └── red/
│       ├── Dockerfile
│       ├── requirements.txt
│       ├── main.py                  # FastAPI app + agent loop
│       ├── agent.py                 # Claude-powered agent with tool calls
│       ├── caldera_client.py        # Caldera REST API wrapper
│       ├── art_index.py             # Loads and searches ART YAML tests
│       └── tools.py                 # Tool definitions for the LLM agent
│
├── attacks/
│   ├── atomics/                     # Git submodule (ART) — create as empty dir
│   │                                # with a README noting: 
│   │                                # `git submodule add https://github.com/redcanaryco/atomic-red-team attacks/atomics`
│   └── custom/                      # Agent-generated attack variants (empty, with .gitkeep)
│
├── detections/
│   ├── sigma/                       # Sigma source rules (empty, with .gitkeep)
│   └── splunk/                      # Compiled SPL rules (empty, with .gitkeep)
│
├── coverage/
│   └── matrix.json                  # Stub coverage matrix (see schema below)
│
└── scripts/
    ├── deploy-detections.py         # Stub — pushes rules to Splunk API
    └── seed-coverage.py             # Stub — loads ATT&CK STIX into matrix
```

---

## File Specifications

### `docker-compose.yml`
- Services: `caldera`, `splunk`, `red-agent`
- `caldera`: use image `mitre/caldera:latest`, expose ports 8888 and 7010,
  mount `./attacks/custom` into `/usr/src/app/data/abilities/custom`,
  named volume for caldera-data
- `splunk`: use image `splunk/splunk:latest`, expose ports 8000, 8089, 9997,
  env vars `SPLUNK_START_ARGS=--accept-license` and `SPLUNK_PASSWORD` from .env,
  named volume for splunk-data
- `red-agent`: build from `./agents/red`, expose port 8001,
  env vars: `CALDERA_URL`, `CALDERA_API_KEY`, `ANTHROPIC_API_KEY`, `ART_PATH=/attacks/atomics`,
  mount `./attacks` as `/attacks`, depends_on caldera

### `.env.example`
Include these keys (empty values):
- `CALDERA_API_KEY`
- `SPLUNK_PASSWORD`
- `ANTHROPIC_API_KEY`

### `agents/red/requirements.txt`
- fastapi
- uvicorn
- httpx
- anthropic
- pyyaml
- pydantic

### `agents/red/Dockerfile`
- Base image: `python:3.12-slim`
- Working dir: `/app`
- Copy and install requirements
- Copy source
- Expose port 8001
- CMD: `uvicorn main:app --host 0.0.0.0 --port 8001`

### `agents/red/caldera_client.py`
Implement a `CalderaClient` class with these methods:
```python
class CalderaClient:
    def __init__(self, base_url: str, api_key: str): ...

    def get_agents(self) -> list[dict]:
        # GET /api/v2/agents
        # Returns list of active sandcat agents with fields:
        # paw, host, platform, last_seen

    def get_abilities(self, technique_id: str = None) -> list[dict]:
        # GET /api/v2/abilities
        # If technique_id provided, filter by ability.technique_id
        # Returns list with fields: ability_id, name, technique_id,
        #   technique_name, tactic, description, platform

    def create_operation(self, name: str, ability_ids: list[str],
                         agent_group: str, planner: str = "atomic") -> str:
        # POST /api/v2/operations
        # Returns operation_id

    def get_operation_status(self, operation_id: str) -> dict:
        # GET /api/v2/operations/{operation_id}
        # Returns: id, name, state, start, finish

    def get_operation_results(self, operation_id: str) -> list[dict]:
        # GET /api/v2/operations/{operation_id}/links
        # Returns list of links, each with:
        # ability.technique_id, ability.name, status, output (stdout decoded
        # from base64), finish
```

All methods should raise a clear exception with the response body on non-2xx.

### `agents/red/art_index.py`
Implement an `ARTIndex` class:
```python
class ARTIndex:
    def __init__(self, art_path: str):
        # art_path is the root of the ART repo
        # Recursively find all atomic YAML files under art_path/atomics/
        # Parse each and build an in-memory index keyed by technique_id

    def list_techniques(self, platform: str = "windows",
                        tactic: str = None) -> list[dict]:
        # Return list of techniques that have at least one test
        # supporting the given platform
        # Each item: technique_id, display_name, test_count
        # tactic filter is best-effort (ART YAMLs don't always include tactic,
        # so filter only when present)

    def get_technique(self, technique_id: str) -> dict | None:
        # Return full parsed YAML for that technique, or None

    def get_test_command(self, technique_id: str,
                         test_index: int = 0,
                         platform: str = "windows") -> str | None:
        # Return the executor command string for the given test index
        # Return None if technique or test not found
```

Handle the case where `art_path` doesn't exist or is empty (ART submodule not
initialised) by logging a warning and returning empty results — don't crash.

### `agents/red/tools.py`
Define the four Claude tool schemas as a Python list of dicts (`TOOLS`):

1. **`list_techniques`**
   - Description: List ATT&CK techniques available in Caldera and/or ART for Windows
   - Inputs: `tactic` (string, optional), `source` (enum: "caldera", "art", "all"; default "all")

2. **`get_technique_detail`**
   - Description: Get full detail on a technique including Caldera abilities and ART test variants
   - Inputs: `technique_id` (string, required)

3. **`run_attack`**
   - Description: Execute a technique on the target via Caldera. Picks the first available ability. Returns operation_id.
   - Inputs: `technique_id` (string, required), `target_agent_paw` (string, required), `ability_id` (string, optional)

4. **`get_operation_result`**
   - Description: Get status and output of a Caldera operation. Returns structured result including whether execution succeeded.
   - Inputs: `operation_id` (string, required)

Also implement `execute_tool(tool_name, tool_input, caldera, art)` — a dispatcher
function that routes tool calls to the right client method and returns a
JSON-serialisable dict.

### `agents/red/agent.py`
Implement the Claude-powered agent loop:

```python
class RedAgent:
    def __init__(self, caldera: CalderaClient, art: ARTIndex):
        self.caldera = caldera
        self.art = art
        self.client = anthropic.Anthropic()
        self.conversation_history = []

    async def chat(self, user_message: str) -> str:
        # Append user message to history
        # Call Claude claude-sonnet-4-20250514 with:
        #   - system prompt (see below)
        #   - full conversation history
        #   - TOOLS list from tools.py
        # Handle tool_use response blocks in a loop:
        #   - execute each tool via execute_tool()
        #   - append tool results to history
        #   - re-call Claude with updated history
        # Continue until Claude returns stop_reason == "end_turn"
        # Return final text response
        # Append full exchange to self.conversation_history
```

System prompt for the agent:
```
You are a red team agent with access to Caldera (a breach and attack simulation 
platform) and Atomic Red Team (a library of adversary techniques).

Your job is to help security engineers test their defences by executing ATT&CK 
techniques on authorised target endpoints.

When a user asks you to run an attack:
1. Identify the most relevant ATT&CK technique(s)
2. Check what abilities are available in Caldera and what tests exist in ART
3. Confirm the target agent with the user if not specified
4. Run the attack and report back clearly: what ran, on what target, 
   whether it succeeded, and the raw output
5. Summarise what a defender should have seen if detections were in place

Always be specific about technique IDs, ability names, and execution output.
Never run attacks without a confirmed target agent paw.
```

### `agents/red/main.py`
FastAPI app with these endpoints:

```python
POST /chat
  Request:  { "message": string }
  Response: { "reply": string, "conversation_id": string }

GET /agents
  Response: { "agents": list[dict] }  # proxies CalderaClient.get_agents()

GET /techniques
  Query params: tactic (optional), source (optional, default "all")
  Response: { "techniques": list[dict] }

GET /health
  Response: { "status": "ok", "caldera_reachable": bool, "art_loaded": bool }
```

Initialise `CalderaClient` and `ARTIndex` at startup using env vars.
The `/chat` endpoint should maintain a single global `RedAgent` instance
(conversation persists in memory for now — multi-session is a later concern).

### `coverage/matrix.json`
Stub with this structure for 5 example techniques:
```json
{
  "last_updated": null,
  "techniques": {
    "T1059.001": {
      "name": "PowerShell",
      "tactic": "execution",
      "tested": false,
      "detected": null,
      "last_run": null,
      "notes": null
    },
    "T1059.003": { ... },
    "T1003.001": { ... },
    "T1055.001": { ... },
    "T1078":     { ... }
  }
}
```

### `scripts/seed-coverage.py`
Stub only. Print a message: "TODO: fetch enterprise-attack STIX bundle from
MITRE, filter Windows techniques with ART coverage, write to coverage/matrix.json"

### `scripts/deploy-detections.py`
Stub only. Print a message: "TODO: read detections/splunk/*.spl, POST each to
Splunk saved searches API"

---

## Constraints and Notes

- All async I/O in the FastAPI app should use `async def` with `httpx.AsyncClient`
- The `ARTIndex` loading is synchronous and runs at startup (it's a local file read)
- Do not implement auth on the FastAPI endpoints for now
- Add docstrings to all classes and public methods
- Add a top-level `README.md` with:
  - One-paragraph description of the project
  - Prerequisites (Docker, git, Python 3.12)
  - Setup instructions (clone, init submodule, copy .env, docker-compose up)
  - How to use the red agent (curl examples for /chat and /techniques)
  - Note that attacks/atomics must be populated via `git submodule update --init`
    before ART features work