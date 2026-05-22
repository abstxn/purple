# Task: Scaffold Red Agent Monorepo (Iteration 1)

## Goal

Build the foundational monorepo structure for an autonomous security validation
platform. This iteration focuses exclusively on the **red agent** — an
LLM-powered service that integrates with Caldera (BAS) and Atomic Red Team (ART)
to execute ATT&CK techniques on a target Windows endpoint.

Caldera runs as a Docker container built from source. ART is a git submodule
bind-mounted into Caldera's atomic plugin directory so Caldera loads it natively
— no custom ART parsing code is needed. Configuration is persistent via a
bind-mounted config file.

---

## Monorepo Structure to Create

```
/
├── docker-compose.yml
├── caldera.Dockerfile
├── .env.example
├── .gitmodules
├── .gitignore
│
├── config/
│   └── caldera.yml                  # Persistent Caldera config, committed to repo
│
├── agents/
│   └── red/
│       ├── Dockerfile
│       ├── requirements.txt
│       ├── main.py                  # FastAPI app
│       ├── agent.py                 # Claude-powered agent with tool calls
│       ├── caldera_client.py        # Caldera REST API wrapper
│       └── tools.py                 # Tool definitions for the LLM agent
│
├── attacks/
│   ├── atomics/                     # Git submodule → ART upstream repo
│   │                                # Bind-mounted into Caldera's atomic plugin
│   └── custom/                      # Agent-generated attack variants
│       └── .gitkeep
│
├── detections/
│   ├── sigma/                       # Sigma source rules
│   │   └── .gitkeep
│   └── splunk/                      # Compiled SPL rules, deployed to Splunk
│       └── .gitkeep
│
├── coverage/
│   └── matrix.json                  # Current coverage state
│
└── scripts/
    ├── deploy-detections.py         # Stub — pushes rules to Splunk API
    └── seed-coverage.py             # Stub — loads ATT&CK STIX into matrix
```

---

## File Specifications

### `.gitmodules`

```ini
[submodule "attacks/atomics"]
    path = attacks/atomics
    url = https://github.com/redcanaryco/atomic-red-team
    shallow = true
```

### `.gitignore`

Include at minimum:
```
.env
__pycache__/
*.pyc
.DS_Store
```

### `caldera.Dockerfile`

Multi-stage build that clones Caldera inside the image — no manual clone needed
on fresh pull. The version is controlled by a build arg passed in from
`docker-compose.yml`.

```dockerfile
FROM python:3.12-slim AS builder

ARG CALDERA_VERSION=5.0.0

RUN apt-get update && apt-get install -y \
    git golang-go curl build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/mitre/caldera.git --recursive \
    --branch ${CALDERA_VERSION} --depth 1 /usr/src/app

WORKDIR /usr/src/app
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim
WORKDIR /usr/src/app
COPY --from=builder /usr/src/app .
COPY --from=builder /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=builder /usr/local/bin /usr/local/bin

EXPOSE 8888 7010 7011 8022
CMD ["python", "server.py", "--insecure"]
```

### `docker-compose.yml`

- Services: `caldera`, `splunk`, `red-agent`
- `caldera`:
  - Build from `caldera.Dockerfile` with `CALDERA_VERSION` build arg (default `5.0.0`)
  - Platform: `linux/amd64` (required for Apple Silicon compatibility)
  - Ports: `8888:8888`, `7010:7010`, `7011:7011`
  - Volumes:
    - `./config/caldera.yml:/usr/src/app/conf/local.yml` — persistent config
    - `./attacks/atomics:/usr/src/app/plugins/atomic/data/atomic-red-team` — ART submodule
    - `./attacks/custom:/usr/src/app/data/abilities/custom` — custom abilities
  - No data volume — ephemeral data is correct for test runs
- `splunk`:
  - Image: `splunk/splunk:latest`
  - Ports: `8000:8000`, `8089:8089`, `9997:9997`
  - Environment: `SPLUNK_START_ARGS=--accept-license`, `SPLUNK_PASSWORD` from `.env`
  - Named volume: `splunk-data:/opt/splunk/var`
- `red-agent`:
  - Build from `./agents/red`
  - Port: `8001:8001`
  - Environment variables (from `.env`):
    - `CALDERA_URL=http://caldera:8888`
    - `CALDERA_API_KEY`
    - `ANTHROPIC_API_KEY`
  - Volumes: `./attacks:/attacks`
  - `depends_on: caldera`

Named volumes block at the bottom: `splunk-data` only (no caldera-data).

### `.env.example`

```
CALDERA_API_KEY=
SPLUNK_PASSWORD=
ANTHROPIC_API_KEY=
```

### `config/caldera.yml`

Minimal Caldera config that sets fixed credentials so they don't regenerate on
every restart. Use placeholder values that the user will fill in — add a comment
at the top saying to copy this file, fill in credentials, and never commit the
filled version (the example is what gets committed).

Include these keys at minimum:
```yaml
host: 0.0.0.0
port: 8888
plugins:
  - stockpile
  - atomic
  - compass
  - debrief
  - response
  - manx
users:
  red:
    red: REPLACE_WITH_PASSWORD
  blue:
    blue: REPLACE_WITH_PASSWORD
api_key_red: REPLACE_WITH_API_KEY
api_key_blue: REPLACE_WITH_API_KEY
```

Add a comment at the top:
```
# Copy this file to config/caldera.yml, fill in your values.
# Do NOT commit config/caldera.yml — only config/caldera.example.yml is committed.
# Add config/caldera.yml to .gitignore.
```

Then update `.gitignore` to also exclude `config/caldera.yml` (but not
`config/caldera.example.yml`).

Rename the committed file to `config/caldera.example.yml` and reference it
accordingly in the README.

### `agents/red/requirements.txt`

```
fastapi
uvicorn
httpx
anthropic
pyyaml
pydantic
```

### `agents/red/Dockerfile`

- Base image: `python:3.12-slim`
- Working dir: `/app`
- Copy and install `requirements.txt`
- Copy source files
- Expose port `8001`
- CMD: `uvicorn main:app --host 0.0.0.0 --port 8001 --reload`

### `agents/red/caldera_client.py`

Implement a `CalderaClient` class. All HTTP calls use `httpx` (sync for now).
Raise a descriptive exception with the response body on any non-2xx response.

```python
class CalderaClient:
    def __init__(self, base_url: str, api_key: str):
        """Initialise with Caldera base URL and API key (red user token)."""

    def get_agents(self) -> list[dict]:
        """
        GET /api/v2/agents
        Returns active sandcat agents. Each item includes:
        paw, host, platform, last_seen, group.
        """

    def get_abilities(self, technique_id: str = None) -> list[dict]:
        """
        GET /api/v2/abilities
        If technique_id is provided, filter results by ability.technique_id.
        Each item includes: ability_id, name, technique_id, technique_name,
        tactic, description, platform.
        """

    def create_operation(
        self,
        name: str,
        ability_ids: list[str],
        agent_group: str,
        planner: str = "atomic"
    ) -> str:
        """
        POST /api/v2/operations
        Creates and starts an operation. Returns the operation_id string.
        """

    def get_operation_status(self, operation_id: str) -> dict:
        """
        GET /api/v2/operations/{operation_id}
        Returns: id, name, state, start, finish.
        """

    def get_operation_results(self, operation_id: str) -> list[dict]:
        """
        GET /api/v2/operations/{operation_id}/links
        Returns list of executed links. Each item includes:
        ability.technique_id, ability.name, status, finish,
        and output (stdout decoded from base64 if present).
        Decode base64 output inside this method before returning.
        """
```

### `agents/red/tools.py`

Define the Claude tool schemas as a Python list of dicts named `TOOLS`.
Also implement an `execute_tool` dispatcher function.

**Tool definitions:**

1. **`list_techniques`**
   - Description: List ATT&CK techniques available in Caldera (including ART
     tests loaded via the atomic plugin) for Windows endpoints.
   - Inputs:
     - `tactic` (string, optional): filter by tactic e.g. "execution",
       "credential-access", "persistence"
     - `source` (string, optional, enum `["caldera", "all"]`, default `"all"`)

2. **`get_technique_detail`**
   - Description: Get full detail on a technique including all available
     Caldera abilities and ART test variants.
   - Inputs:
     - `technique_id` (string, required): ATT&CK technique ID e.g. "T1059.001"

3. **`run_attack`**
   - Description: Execute a technique on the target endpoint via Caldera.
     If no ability_id is specified, uses the first available ability for the
     technique. Returns the operation_id for polling.
   - Inputs:
     - `technique_id` (string, required)
     - `target_agent_paw` (string, required): Caldera agent paw identifier
     - `ability_id` (string, optional): specific ability to run

4. **`get_operation_result`**
   - Description: Get the current status and full output of a Caldera
     operation. Returns structured result including whether execution
     succeeded and raw stdout.
   - Inputs:
     - `operation_id` (string, required)

**Dispatcher:**

```python
def execute_tool(
    tool_name: str,
    tool_input: dict,
    caldera: CalderaClient
) -> dict:
    """
    Route a tool call from the LLM to the correct CalderaClient method.
    Returns a JSON-serialisable dict in all cases.
    Wrap all calls in try/except and return {"error": str(e)} on failure.
    """
```

### `agents/red/agent.py`

Implement the Claude-powered agent loop.

```python
class RedAgent:
    def __init__(self, caldera: CalderaClient):
        self.caldera = caldera
        self.client = anthropic.Anthropic()
        self.conversation_history: list[dict] = []

    async def chat(self, user_message: str) -> str:
        """
        Process a user message through the agent loop.

        1. Append user message to conversation_history
        2. Call Claude (model: claude-sonnet-4-20250514) with:
           - system prompt (see below)
           - full conversation_history
           - TOOLS from tools.py
        3. If response contains tool_use blocks:
           - Execute each tool via execute_tool()
           - Append assistant message and tool results to history
           - Re-call Claude with updated history
           - Repeat until stop_reason == "end_turn"
        4. Append final assistant message to history
        5. Return the final text response string
        """
```

**System prompt:**

```
You are a red team agent with access to Caldera, a breach and attack simulation
platform. Caldera has Atomic Red Team tests loaded natively via its atomic plugin,
so all ART techniques are available through the standard Caldera abilities API.

Your job is to help security engineers test their defences by executing ATT&CK
techniques on authorised target endpoints.

When a user asks you to run an attack:
1. Identify the most relevant ATT&CK technique(s) for their request
2. Use list_techniques to find what is available, then get_technique_detail
   for specifics
3. If the user has not specified a target, use list_techniques to show available
   agents and ask them to confirm before proceeding
4. Run the attack with run_attack and poll with get_operation_result
5. Report back clearly: technique ID and name, ability used, target host,
   whether execution succeeded (exit code), and the raw output
6. Summarise what a defender should have seen if detections were in place

Always be specific about technique IDs and ability names.
Never run attacks without a confirmed target agent paw.
If an operation is still running, poll get_operation_result again rather than
giving up.
```

### `agents/red/main.py`

FastAPI app with the following endpoints. Initialise `CalderaClient` and
`RedAgent` at startup using environment variables. Use a single global
`RedAgent` instance (conversation persists in memory for now).

```
GET  /health
     Response: {
       "status": "ok",
       "caldera_reachable": bool  # result of a lightweight ping to Caldera
     }

GET  /agents
     Response: { "agents": list[dict] }
     Proxies CalderaClient.get_agents()

GET  /techniques
     Query params: tactic (string, optional)
     Response: { "techniques": list[dict] }
     Proxies CalderaClient.get_abilities() with optional tactic filter

POST /chat
     Request:  { "message": string }
     Response: { "reply": string }
     Calls RedAgent.chat() and returns the text response
```

All route functions should be `async def`. Use `httpx.AsyncClient` inside
`CalderaClient` for the `/health` ping. Add basic error handling — if Caldera
is unreachable, `/health` should return `caldera_reachable: false` without
crashing.

### `coverage/matrix.json`

Stub with this exact structure for 5 example techniques:

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
    "T1059.003": {
      "name": "Windows Command Shell",
      "tactic": "execution",
      "tested": false,
      "detected": null,
      "last_run": null,
      "notes": null
    },
    "T1003.001": {
      "name": "LSASS Memory",
      "tactic": "credential-access",
      "tested": false,
      "detected": null,
      "last_run": null,
      "notes": null
    },
    "T1055.001": {
      "name": "DLL Injection",
      "tactic": "defense-evasion",
      "tested": false,
      "detected": null,
      "last_run": null,
      "notes": null
    },
    "T1078": {
      "name": "Valid Accounts",
      "tactic": "persistence",
      "tested": false,
      "detected": null,
      "last_run": null,
      "notes": null
    }
  }
}
```

### `scripts/seed-coverage.py`

Stub only. Print:
```
TODO: Fetch enterprise-attack STIX bundle from MITRE GitHub, filter for
Windows-platform techniques that have Atomic Red Team coverage, and write
to coverage/matrix.json.
```

### `scripts/deploy-detections.py`

Stub only. Print:
```
TODO: Read all .spl files from detections/splunk/, POST each to Splunk
saved searches API at http://<splunk_host>:8089/services/saved/searches.
```

---

## README.md

Write a top-level README with these sections:

### Description
One paragraph: this is an autonomous security validation platform. Iteration 1
provides a red agent that integrates with Caldera and Atomic Red Team to execute
ATT&CK techniques on Windows endpoints via a conversational LLM interface.

### Architecture
Short ASCII diagram showing: Red Agent (FastAPI) → Caldera (Docker) → Windows
Endpoint (Sandcat + Sysmon + Splunk UF). Note that Splunk and blue agent are
iteration 2.

### Prerequisites
- Docker and Docker Compose
- Git
- An Anthropic API key
- A Windows VM with Caldera sandcat agent installed (for actual attack execution)

### Setup

```bash
# 1. Clone the repo
git clone <your-repo-url>
cd <repo>

# 2. Initialise the ART submodule
git submodule update --init --recursive

# 3. Set up config
cp .env.example .env
# Fill in CALDERA_API_KEY and ANTHROPIC_API_KEY in .env

cp config/caldera.example.yml config/caldera.yml
# Fill in credentials in config/caldera.yml

# 4. Build and start
docker-compose up --build
```

### Usage

**Check everything is up:**
```bash
curl http://localhost:8001/health
```

**List available techniques:**
```bash
curl "http://localhost:8001/techniques?tactic=execution"
```

**Chat with the red agent:**
```bash
curl -X POST http://localhost:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What credential dumping techniques are available?"}'
```

**Run an attack:**
```bash
curl -X POST http://localhost:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Run a PowerShell execution test on agent abc123"}'
```

### Notes
- `attacks/atomics` must be initialised via `git submodule update --init`
  before ART techniques appear in Caldera
- Caldera data is ephemeral by default — it resets on container restart.
  This is intentional for clean test runs.
- The `builder` plugin is disabled in Docker per Caldera's official guidance.
- The Windows target VM needs the Caldera sandcat agent running and reachable
  on port 7010 of the host running Docker.

---

## Constraints

- All FastAPI route functions must be `async def`
- Do not add authentication to the FastAPI endpoints in this iteration
- Add docstrings to all classes and public methods
- The `ARTIndex` class from the previous task spec is **not needed** — Caldera
  loads ART natively via the atomic plugin. Do not implement it.
- Do not use `subprocess` or shell execution anywhere in the agent code —
  all attack execution goes through the Caldera API
- Handle the case where Caldera is unreachable gracefully in all endpoints