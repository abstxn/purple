"""OpenAI-format tool schemas and execution dispatcher for the red agent."""

from __future__ import annotations

from caldera_client import CalderaClient

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

_TOOLS: list[dict] = [
    {
        "name": "list_techniques",
        "description": (
            "List ATT&CK techniques available in Caldera (including ART tests "
            "loaded via the atomic plugin) for Windows endpoints."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tactic": {
                    "type": "string",
                    "description": (
                        "Optional tactic filter, e.g. execution, "
                        "credential-access, persistence"
                    ),
                },
                "source": {
                    "type": "string",
                    "enum": ["caldera", "all"],
                    "description": "Technique source (default: all)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_technique_detail",
        "description": (
            "Get full detail on a technique including all available "
            "Caldera abilities and ART test variants."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "technique_id": {
                    "type": "string",
                    "description": 'ATT&CK technique ID, e.g. "T1059.001"',
                },
            },
            "required": ["technique_id"],
        },
    },
    {
        "name": "run_attack",
        "description": (
            "Execute a technique on the target endpoint via Caldera. "
            "If no ability_id is specified, uses the first available ability. "
            "Returns the operation_id for polling."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "technique_id": {
                    "type": "string",
                    "description": "ATT&CK technique ID to run",
                },
                "target_agent_paw": {
                    "type": "string",
                    "description": "Caldera agent paw identifier",
                },
                "ability_id": {
                    "type": "string",
                    "description": "Optional specific Caldera ability ID",
                },
            },
            "required": ["technique_id", "target_agent_paw"],
        },
    },
    {
        "name": "get_operation_result",
        "description": (
            "Get the current status and full output of a Caldera operation. "
            "Returns structured result including whether execution succeeded "
            "and raw stdout."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "operation_id": {
                    "type": "string",
                    "description": "Caldera operation ID",
                },
            },
            "required": ["operation_id"],
        },
    },
]

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["parameters"],
        },
    }
    for tool in _TOOLS
]


def execute_tool(
    tool_name: str,
    tool_input: dict,
    caldera: CalderaClient,
) -> dict:
    """Route a tool call to the correct CalderaClient method."""
    try:
        if tool_name == "list_techniques":
            return _list_techniques(tool_input, caldera)
        if tool_name == "get_technique_detail":
            return _get_technique_detail(tool_input, caldera)
        if tool_name == "run_attack":
            return _run_attack(tool_input, caldera)
        if tool_name == "get_operation_result":
            return _get_operation_result(tool_input, caldera)
        return {"error": f"Unknown tool: {tool_name}"}
    except Exception as exc:
        return {"error": str(exc)}


def _is_windows_ability(ability: dict) -> bool:
    """Return True if the ability targets Windows."""
    platform = ability.get("platform")
    if platform is None:
        return True
    if isinstance(platform, str):
        return platform.lower() == "windows"
    if isinstance(platform, dict):
        return "windows" in {k.lower() for k in platform}
    if isinstance(platform, list):
        return any(str(p).lower() == "windows" for p in platform)
    return True


def _list_techniques(tool_input: dict, caldera: CalderaClient) -> dict:
    tactic = tool_input.get("tactic")
    source = tool_input.get("source", "all")
    if source not in ("caldera", "all"):
        return {"error": f"Invalid source: {source}. Use 'caldera' or 'all'."}

    abilities = caldera.get_abilities()
    techniques: dict[str, dict] = {}
    for ability in abilities:
        if not _is_windows_ability(ability):
            continue
        if tactic and ability.get("tactic"):
            if ability["tactic"].lower() != tactic.lower():
                continue
        tid = ability.get("technique_id")
        if not tid:
            continue
        if tid not in techniques:
            techniques[tid] = {
                "technique_id": tid,
                "name": ability.get("technique_name") or tid,
                "tactic": ability.get("tactic"),
                "ability_count": 0,
            }
        techniques[tid]["ability_count"] += 1

    return {
        "techniques": sorted(techniques.values(), key=lambda x: x["technique_id"])
    }


def _get_technique_detail(tool_input: dict, caldera: CalderaClient) -> dict:
    technique_id = tool_input["technique_id"]
    abilities = caldera.get_abilities(technique_id=technique_id)
    windows_abilities = [a for a in abilities if _is_windows_ability(a)]
    return {
        "technique_id": technique_id,
        "abilities": windows_abilities or abilities,
        "ability_count": len(windows_abilities or abilities),
    }


def _run_attack(tool_input: dict, caldera: CalderaClient) -> dict:
    technique_id = tool_input["technique_id"]
    target_paw = tool_input["target_agent_paw"]
    ability_id = tool_input.get("ability_id")

    agents = caldera.get_agents()
    agent = next((a for a in agents if a.get("paw") == target_paw), None)
    if not agent:
        return {
            "error": f"No agent found with paw {target_paw}",
            "available_agents": agents,
        }

    abilities = [
        a
        for a in caldera.get_abilities(technique_id=technique_id)
        if _is_windows_ability(a)
    ]
    if not abilities:
        return {"error": f"No Caldera abilities found for {technique_id}"}

    if ability_id:
        selected = next(
            (a for a in abilities if a.get("ability_id") == ability_id), None
        )
        if not selected:
            return {
                "error": f"Ability {ability_id} not found for {technique_id}",
                "available_abilities": abilities,
            }
    else:
        selected = abilities[0]

    aid = selected["ability_id"]
    group = agent.get("group") or "red"
    op_name = f"red-agent-{technique_id}-{target_paw[:8]}"
    operation_id = caldera.create_operation(
        name=op_name,
        ability_ids=[aid],
        agent_group=group,
    )
    return {
        "operation_id": operation_id,
        "technique_id": technique_id,
        "ability_id": aid,
        "ability_name": selected.get("name"),
        "target_agent_paw": target_paw,
        "target_host": agent.get("host"),
    }


def _get_operation_result(tool_input: dict, caldera: CalderaClient) -> dict:
    operation_id = tool_input["operation_id"]
    status = caldera.get_operation_status(operation_id)
    links = caldera.get_operation_results(operation_id)
    succeeded = any(
        (link.get("status") or "").lower() in ("success", "completed", "0")
        for link in links
    )
    return {
        "operation_id": operation_id,
        "status": status,
        "links": links,
        "succeeded": succeeded,
    }
