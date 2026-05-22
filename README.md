# Purple

Purple is an autonomous security validation platform. Iteration 1 provides a red
agent that integrates with Caldera and Atomic Red Team to execute MITRE ATT&CK
techniques on Windows endpoints via a conversational LLM interface.

## Architecture

```
┌─────────────────┐     REST API      ┌──────────────────┐     Sandcat (7010)
│   Red Agent     │ ────────────────► │     Caldera      │ ──────────────────►
│   (FastAPI)     │                   │    (Docker)      │   Windows Endpoint
│   :8001         │                   │    :8888         │   + Sysmon + Splunk UF
└─────────────────┘                   └──────────────────┘
                                              │
                                              │ atomic plugin
                                              ▼
                                      attacks/atomics (ART submodule)

Splunk (:8000) and blue agent — iteration 2.
```

## Prerequisites

- Docker and Docker Compose
- Git
- [Ollama](https://ollama.com/) running on the host with `llama3.1:8b` pulled
- A Windows VM with the Caldera sandcat agent installed (for actual attack execution)

## Setup

```bash
# 1. Clone the repo
git clone <your-repo-url>
cd <repo>

# 2. Initialise the ART submodule
git submodule update --init --recursive

# 3. Start Ollama on the host and pull the model
brew services start ollama   # macOS
ollama pull llama3.1:8b

# 4. Set up config
cp .env.example .env
# Fill in CALDERA_API_KEY in .env (OLLAMA_* defaults work for Docker Desktop)

cp config/caldera.example.yml config/caldera.yml
# Fill in credentials in config/caldera.yml

# 5. Build and start
docker compose up --build
```

Caldera UI: http://localhost:8888  
Splunk UI: http://localhost:8000  
Red agent API: http://localhost:8001

Set `CALDERA_API_KEY` in `.env` to the value of `api_key_red` from `config/caldera.yml`.

## Usage

**Check everything is up:**

```bash
curl http://localhost:8001/health
```

**List available techniques:**

```bash
curl "http://localhost:8001/techniques?tactic=execution"
```

**List Caldera agents:**

```bash
curl http://localhost:8001/agents
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

**Reset conversation history (development):**

```bash
curl -X POST http://localhost:8001/reset
```

## Notes

- `attacks/atomics` must be initialised via `git submodule update --init` before
  ART techniques appear in Caldera.
- Caldera data is ephemeral by default — it resets on container restart. This is
  intentional for clean test runs.
- The `builder` plugin is disabled in Docker per Caldera's official guidance.
- The Windows target VM needs the Caldera sandcat agent running and reachable on
  port 7010 of the host running Docker.
- Do not commit `config/caldera.yml` — only `config/caldera.example.yml` is tracked.
- Ollama runs on the host, not in Docker. The red-agent container reaches it via
  `host.docker.internal:11434`. Set `OLLAMA_MODEL=qwen2.5:7b` in `.env` if tool
  calls fail with `llama3.1:8b`.
