"""Caldera REST API v2 client."""

from __future__ import annotations

import base64
from typing import Any

import httpx


class CalderaError(Exception):
    """Raised when the Caldera API returns a non-success response."""


class CalderaClient:
    """Synchronous wrapper around the Caldera REST API v2."""

    def __init__(self, base_url: str, api_key: str):
        """Initialise with Caldera base URL and API key (red user token)."""
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._headers = {"KEY": api_key}

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
    ) -> Any:
        """Perform an HTTP request and return parsed JSON."""
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=60.0) as client:
            response = client.request(
                method,
                url,
                headers=self._headers,
                json=json,
                params=params,
            )
        if not response.is_success:
            raise CalderaError(
                f"{method} {path} failed ({response.status_code}): {response.text}"
            )
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def get_agents(self) -> list[dict]:
        """Return active sandcat agents (paw, host, platform, last_seen, group)."""
        data = self._request("GET", "/api/v2/agents")
        agents = data if isinstance(data, list) else data.get("agents", data) or []
        return [
            {
                "paw": a.get("paw"),
                "host": a.get("host"),
                "platform": a.get("platform"),
                "last_seen": a.get("last_seen"),
                "group": a.get("group"),
            }
            for a in agents
        ]

    def get_abilities(self, technique_id: str | None = None) -> list[dict]:
        """Return abilities, optionally filtered by ATT&CK technique ID."""
        data = self._request("GET", "/api/v2/abilities")
        abilities = data if isinstance(data, list) else data.get("abilities", data) or []
        result = []
        for ability in abilities:
            tid = ability.get("technique_id") or ability.get("technique", {}).get(
                "attack_id"
            )
            if technique_id and tid != technique_id:
                continue
            result.append(
                {
                    "ability_id": ability.get("ability_id") or ability.get("id"),
                    "name": ability.get("name"),
                    "technique_id": tid,
                    "technique_name": ability.get("technique_name")
                    or ability.get("technique", {}).get("name"),
                    "tactic": ability.get("tactic"),
                    "description": ability.get("description"),
                    "platform": ability.get("platform"),
                }
            )
        return result

    def create_operation(
        self,
        name: str,
        ability_ids: list[str],
        agent_group: str,
        planner: str = "atomic",
    ) -> str:
        """Create and start an operation; return the operation ID."""
        payload = {
            "name": name,
            "group": agent_group,
            "planner": planner,
            "auto_close": True,
            "state": "running",
            "adversary": {
                "name": name,
                "description": f"Auto-created for {name}",
                "atomic_ordering": ability_ids,
                "abilities": ability_ids,
            },
        }
        data = self._request("POST", "/api/v2/operations", json=payload)
        if isinstance(data, dict):
            return data.get("id") or data.get("operation_id") or str(data)
        return str(data)

    def get_operation_status(self, operation_id: str) -> dict:
        """Return operation status fields."""
        data = self._request("GET", f"/api/v2/operations/{operation_id}")
        return {
            "id": data.get("id"),
            "name": data.get("name"),
            "state": data.get("state"),
            "start": data.get("start"),
            "finish": data.get("finish"),
        }

    def get_operation_results(self, operation_id: str) -> list[dict]:
        """Return operation links with decoded stdout output."""
        data = self._request("GET", f"/api/v2/operations/{operation_id}/links")
        links = data if isinstance(data, list) else data.get("links", data) or []
        results = []
        for link in links:
            ability = link.get("ability") or {}
            raw_output = link.get("output") or link.get("stdout") or ""
            if raw_output:
                try:
                    output = base64.b64decode(raw_output).decode(
                        "utf-8", errors="replace"
                    )
                except Exception:
                    output = raw_output
            else:
                output = ""
            results.append(
                {
                    "ability": {
                        "technique_id": ability.get("technique_id"),
                        "name": ability.get("name"),
                    },
                    "status": link.get("status") or link.get("state"),
                    "output": output,
                    "finish": link.get("finish"),
                }
            )
        return results
