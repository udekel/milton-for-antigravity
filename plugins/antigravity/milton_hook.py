#!/usr/bin/env python3
"""Milton JSON Hook Executor for Jetski / Antigravity harness.

This script is invoked directly by Jetski via hooks.json.
It connects to the local Milton Agent Backend API (http://127.0.0.1:8000)
to stream event fragments, fetch summaries, and request rationale explanations.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path so app imports work regardless of CWD
REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

API_URL = os.getenv("MILTON_API_URL", "http://127.0.0.1:8000").rstrip("/")
LOG_FILE = "/tmp/milton_hook.log"


def log_event(msg: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass


from app.utils.tracing import get_trace_headers




def http_post(path: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    url = f"{API_URL}{path}"
    try:
        data_bytes = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        headers.update(get_trace_headers())
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log_event(f"HTTP POST {path} error: {e}")
    return None


def http_get(path: str) -> Optional[Dict[str, Any]]:
    url = f"{API_URL}{path}"
    try:
        headers = {"Content-Type": "application/json"}
        headers.update(get_trace_headers())
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log_event(f"HTTP GET {path} error: {e}")
    return None



def extract_mutterings_rationale_from_transcript(transcript_path: str, tool_name: str, tool_args: Dict[str, Any]) -> str:
    """Extracts recent thinking from transcript file to produce a concise 1-3 sentence rationale."""
    recent_thoughts = []
    if transcript_path and os.path.exists(transcript_path):
        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
            for line in reversed(lines[-15:]):
                entry = json.loads(line)
                thinking = entry.get("thinking") or (entry.get("content") if entry.get("type") in ("PLANNER_RESPONSE", "MODEL") else None)
                if thinking and isinstance(thinking, str) and len(thinking.strip()) > 10:
                    thought = thinking.strip().replace("\n", " ")
                    if "The user says:" in thought:
                        thought = thought.split("The user says:")[-1].strip()
                    recent_thoughts.append(thought)
                    break
        except Exception as e:
            log_event(f"Error reading transcript for rationale: {e}")

    thought_str = recent_thoughts[0] if recent_thoughts else ""
    if len(thought_str) > 150:
        thought_str = thought_str[:147] + "..."
    if thought_str and not thought_str.endswith("."):
        thought_str += "."

    if tool_name == "run_command":
        cmd = (tool_args or {}).get("CommandLine", "")
        cmd_str = f"Executing shell command `{cmd[:90]}`." if cmd else "Executing shell command."
        return f"{thought_str} {cmd_str}".strip() if thought_str else cmd_str
    elif tool_name in ("write_file", "replace_file_content", "multi_replace_file_content", "write_to_file"):
        target = (tool_args or {}).get("TargetFile", "")
        file_name = target.split("/")[-1] if target else "workspace file"
        mod_str = f"Applying code modifications to {file_name}."
        return f"{thought_str} {mod_str}".strip() if thought_str else mod_str

    tool_str = f"Executing tool '{tool_name}'."
    return f"{thought_str} {tool_str}".strip() if thought_str else tool_str


def handle_pre_tool_use(session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Fires BEFORE tool execution. Queries Milton server or local transcript for rationale, returning decision='ask' for permission-gated tools to defer to user modal."""
    tool_call = payload.get("toolCall", {})
    tool_name = tool_call.get("name", "unknown_tool")
    tool_args = tool_call.get("args", {})
    transcript_path = payload.get("transcriptPath", "")

    log_event(f"Handling PreToolUse for tool '{tool_name}' in session '{session_id}'")

    # Sync recent transcript fragments to local Milton server if present
    sync_transcript_to_milton_server(session_id, transcript_path)

    # Attempt to fetch explanation rationale from local Milton server
    encoded_tool = urllib.parse.quote(tool_name)
    res = http_get(f"/api/v1/session/{session_id}/explain-request?target_tool={encoded_tool}")

    if res and "explanation" in res:
        rationale = res["explanation"]
    else:
        # Robust fallback: extract rationale locally from transcript or tool signature
        rationale = extract_mutterings_rationale_from_transcript(transcript_path, tool_name, tool_args)

    reason_text = f"[Milton Rationale]\n{rationale}"

    # Only return decision='ask' for permission-gated / interactive prompt tools
    # to avoid blocking internal workspace operations (view_file, replace_file_content, etc.)
    if tool_name in ("run_command", "read_url", "ask_permission", "execute_url"):
        decision = "ask"
    else:
        decision = "allow"

    return {
        "decision": decision,
        "reason": reason_text
    }






def handle_post_invocation(session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Fires at turn completion. Fetches server-generated summary and injects into UI."""
    log_event(f"Handling PostInvocation for session '{session_id}'")
    transcript_path = payload.get("transcriptPath", "")

    # Sync latest trajectory to local Milton server
    sync_transcript_to_milton_server(session_id, transcript_path)

    # Fetch summary from Milton server
    res = http_get(f"/api/v1/session/{session_id}/summary")

    if res and "human_summary" in res:
        actions = ", ".join(res.get("actions_executed", [])) or "General reasoning"
        summary_text = (
            "[Milton Summary of Mutterings]\n"
            f"{res['human_summary']}\n"
            f"Actions executed: {actions}"
        )
    else:
        summary_text = (
            "[Milton Summary of Mutterings (Offline - Could not connect to Milton Server)]\n"
            "Processed turn mutterings from local transcript log."
        )

    return {
        "injectSteps": [
            {
                "userMessage": summary_text
            },
            {
                "ephemeralMessage": summary_text
            }
        ],
        "summary": summary_text,
        "userMessage": summary_text,
        "message": summary_text,
        "terminationBehavior": ""
    }







def main():
    try:
        input_data = sys.stdin.read()
        log_event(f"Milton Hook Called. Input length: {len(input_data)}")

        if not input_data:
            json.dump({}, sys.stdout)
            return

        payload = json.loads(input_data)
        session_id = payload.get("conversationId") or payload.get("common", {}).get("conversationId") or "session-default"

        # Ensure session is initialized on local Milton server
        http_post("/api/v1/session/start", {"session_id": session_id})

        if "toolCall" in payload:
            result = handle_pre_tool_use(session_id, payload)
            if "reason" in result and result["reason"]:
                sys.stderr.write(f"\n{result['reason']}\n\n")
                sys.stderr.flush()
        else:
            result = handle_post_invocation(session_id, payload)
            if "summary" in result and result["summary"]:
                sys.stderr.write(f"\n{result['summary']}\n\n")
                sys.stderr.flush()

        json.dump(result, sys.stdout)
        sys.stdout.flush()

    except Exception as e:
        log_event(f"Exception in main: {e}")
        json.dump({}, sys.stdout)


if __name__ == "__main__":
    main()
