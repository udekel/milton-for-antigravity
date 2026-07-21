import json
import logging
import urllib.parse
import urllib.request
from enum import Enum
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="[Milton Plugin] %(asctime)s - %(levelname)s - %(message)s")


class MiltonMode(str, Enum):
    OFF = "OFF"
    SUMMARIZE_EVERYTHING = "SUMMARIZE_EVERYTHING"
    ONLY_EXPLAIN_REQUESTS = "ONLY_EXPLAIN_REQUESTS"


class MiltonAntigravityPlugin:
    """Milton Client Plugin for Antigravity / Jetski harness.
    
    Connects to the local Milton Agent Backend API (default http://127.0.0.1:8000)
    to transmit fragments/turns and retrieve server-generated summaries and permission rationales.
    """

    def __init__(self, mode: MiltonMode = MiltonMode.SUMMARIZE_EVERYTHING, api_url: str = "http://127.0.0.1:8000"):
        self.mode = mode
        self.api_url = api_url.rstrip("/")
        self.session_id: Optional[str] = None
        self.current_fragments: List[Dict[str, Any]] = []

    def _http_post(self, path: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        url = f"{self.api_url}{path}"
        try:
            data_bytes = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data_bytes, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logging.warning(f"Milton API POST {path} failed: {e}")
        return None

    def _http_get(self, path: str) -> Optional[Dict[str, Any]]:
        url = f"{self.api_url}{path}"
        try:
            req = urllib.request.Request(url, headers={"Content-Type": "application/json"}, method="GET")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logging.warning(f"Milton API GET {path} failed: {e}")
        return None

    def on_session_start(self, session_id: str, workspace_paths: List[str]):
        """Hook called when a new coding session starts."""
        self.session_id = session_id
        self.current_fragments.clear()
        
        if self.mode == MiltonMode.OFF:
            return

        res = self._http_post("/api/v1/session/start", {
            "session_id": session_id,
            "workspace_paths": workspace_paths
        })
        if res:
            logging.info(f"Connected to local Milton server. Session: {session_id}")
        else:
            logging.warning(f"Local Milton server offline at {self.api_url}. Operating in standby mode.")

    def on_user_prompt(self, prompt: str):
        """Hook called when user submits a prompt."""
        if self.mode == MiltonMode.OFF or not self.session_id:
            return

        frag = {"type": "user_prompt", "content": prompt}
        self.current_fragments.append(frag)
        self._http_post(f"/api/v1/session/{self.session_id}/fragment", frag)

    def on_muttering(self, thinking_content: str):
        """Hook called whenever intermediate thought / stream of thought occurs."""
        if self.mode == MiltonMode.OFF or not self.session_id:
            return

        frag = {"type": "muttering", "content": thinking_content}
        self.current_fragments.append(frag)
        self._http_post(f"/api/v1/session/{self.session_id}/fragment", frag)

    def on_pre_tool_call(self, tool_name: str, tool_args: Dict[str, Any], step_idx: int) -> Optional[Dict[str, Any]]:
        """Pre-tool execution hook. Queries local Milton server for permission request explanation."""
        if self.mode == MiltonMode.OFF or not self.session_id:
            return None

        frag = {
            "type": "pre_tool_call",
            "tool_name": tool_name,
            "args": tool_args,
            "step_idx": step_idx
        }
        self.current_fragments.append(frag)
        self._http_post(f"/api/v1/session/{self.session_id}/fragment", frag)

        if self.mode in (MiltonMode.ONLY_EXPLAIN_REQUESTS, MiltonMode.SUMMARIZE_EVERYTHING):
            if tool_name in ("run_command", "write_file", "ask_permission"):
                encoded_args = urllib.parse.quote(json.dumps(tool_args))
                res = self._http_get(f"/api/v1/session/{self.session_id}/explain-request?target_tool={tool_name}&tool_args={encoded_args}")
                if res and "explanation" in res:
                    explanation_text = res["explanation"]
                    return {
                        "decision": "force_ask",
                        "reason": explanation_text,
                        "injected_message": explanation_text
                    }
        return None

    def on_post_tool_call(self, tool_name: str, tool_output: str, error: Optional[str] = None):
        """Post-tool execution hook."""
        if self.mode == MiltonMode.OFF or not self.session_id:
            return

        frag = {
            "type": "post_tool_call",
            "tool_name": tool_name,
            "error": error,
            "output_preview": tool_output[:100] if tool_output else None
        }
        self.current_fragments.append(frag)
        self._http_post(f"/api/v1/session/{self.session_id}/fragment", frag)

    def on_turn_complete(self, final_response: str) -> Optional[str]:
        """Hook called when turn finishes. Fetches server-generated summary of mutterings."""
        if self.mode == MiltonMode.OFF or not self.session_id:
            return None

        if self.mode == MiltonMode.SUMMARIZE_EVERYTHING:
            res = self._http_get(f"/api/v1/session/{self.session_id}/summary")
            if res and "human_summary" in res:
                actions = ", ".join(res.get("actions_executed", [])) or "None"
                
                return (
                    "\n" + "="*65 + "\n"
                    "Milton Summary of Mutterings:\n"
                    f"{res['human_summary']}\n"
                    f"Actions Executed: {actions}\n"
                    + "="*65 + "\n"
                )
        return None

