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
from typing import Any, Dict, List, Optional

API_URL = os.getenv("MILTON_API_URL", "http://127.0.0.1:8000").rstrip("/")
LOG_FILE = "/tmp/milton_hook.log"


def log_event(msg: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass


def http_post(path: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    url = f"{API_URL}{path}"
    try:
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data_bytes, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log_event(f"HTTP POST {path} error: {e}")
    return None


def http_get(path: str) -> Optional[Dict[str, Any]]:
    url = f"{API_URL}{path}"
    try:
        req = urllib.request.Request(url, headers={"Content-Type": "application/json"}, method="GET")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log_event(f"HTTP GET {path} error: {e}")
    return None


def extract_mutterings_rationale_from_transcript(transcript_path: str, tool_name: str, tool_args: Dict[str, Any]) -> str:
    """Extracts recent thinking from transcript file to produce a meaningful rationale."""
    recent_thoughts = []
    if transcript_path and os.path.exists(transcript_path):
        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
            for line in reversed(lines[-15:]):
                entry = json.loads(line)
                thinking = entry.get("thinking") or (entry.get("content") if entry.get("type") in ("PLANNER_RESPONSE", "MODEL") else None)
                if thinking and isinstance(thinking, str) and len(thinking.strip()) > 10:
                    recent_thoughts.append(thinking.strip())
                    break
        except Exception as e:
            log_event(f"Error reading transcript for rationale: {e}")

    if recent_thoughts:
        thought = recent_thoughts[0].replace("\n", " ")
        if len(thought) > 200:
            thought = thought[:197] + "..."
        return f"Needed to support action: {thought}"

    if tool_name == "run_command":
        cmd = (tool_args or {}).get("CommandLine", "")
        if "pytest" in cmd or "test" in cmd:
            return "Needed to execute test suite and verify implementation."
        elif "git" in cmd:
            return "Needed to inspect or update git repository state."
        elif cmd:
            return f"Needed to run shell command '{cmd[:80]}' for turn execution."
        return "Needed to execute shell diagnostic or build command."
    elif tool_name in ("write_file", "replace_file_content", "multi_replace_file_content"):
        target = (tool_args or {}).get("TargetFile", "")
        file_name = target.split("/")[-1] if target else "workspace file"
        return f"Needed to apply requested code edits to {file_name}."
    elif tool_name == "delete_file":
        return "Needed to remove obsolete workspace files."
    
    return f"Needed to execute tool '{tool_name}' to proceed with task objective."


def sync_transcript_to_milton_server(session_id: str, transcript_path: str):
    """Reads trajectory transcript log file and syncs recent fragments to local Milton server."""
    if not transcript_path or not os.path.exists(transcript_path):
        return

    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]

        for line in lines[-10:]:
            try:
                entry = json.loads(line)
                step_type = entry.get("type")

                # Sync intermediate stream of thought / mutterings
                thinking = entry.get("thinking")
                if thinking:
                    http_post(f"/api/v1/session/{session_id}/fragment", {
                        "type": "muttering",
                        "content": thinking
                    })

                content = entry.get("content")
                if content and not thinking and step_type in ("PLANNER_RESPONSE", "MODEL"):
                    http_post(f"/api/v1/session/{session_id}/fragment", {
                        "type": "muttering",
                        "content": content
                    })

                for tc in entry.get("tool_calls", []):
                    if isinstance(tc, dict):
                        http_post(f"/api/v1/session/{session_id}/fragment", {
                            "type": "pre_tool_call",
                            "tool_name": tc.get("name") or tc.get("type", "tool"),
                            "args": tc.get("args")
                        })
            except Exception:
                continue
    except Exception as e:
        log_event(f"Transcript sync error: {e}")


def handle_pre_tool_use(session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Fires BEFORE tool execution. Queries Milton server for permission rationale explanation."""
    tool_call = payload.get("toolCall", {})
    tool_name = tool_call.get("name", "")
    tool_args = tool_call.get("args", {})
    transcript_path = payload.get("transcriptPath", "")
    log_event(f"Handling PreToolUse for tool '{tool_name}' in session '{session_id}'")

    # Sync latest transcript trajectory first
    sync_transcript_to_milton_server(session_id, transcript_path)

    # Send pre_tool_call fragment to local server
    http_post(f"/api/v1/session/{session_id}/fragment", {
        "type": "pre_tool_call",
        "tool_name": tool_name,
        "args": tool_args
    })

    # Query server for permission explanation
    encoded_args = urllib.parse.quote(json.dumps(tool_args))
    res = http_get(f"/api/v1/session/{session_id}/explain-request?target_tool={tool_name}&tool_args={encoded_args}")

    if res and "explanation" in res and res["explanation"]:
        explanation_text = f"[Milton Rationale]\n{res['explanation']}"
    else:
        rationale = extract_mutterings_rationale_from_transcript(transcript_path, tool_name, tool_args)
        explanation_text = f"[Milton Rationale (Offline - Could not connect to Milton Server)]\n{rationale}"

    return {
        "decision": "force_ask",
        "reason": explanation_text,
        "message": explanation_text,
        "injected_message": explanation_text,
        "user_message": explanation_text
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
        else:
            result = handle_post_invocation(session_id, payload)

        json.dump(result, sys.stdout)
        sys.stdout.flush()
    except Exception as e:
        log_event(f"Exception in main: {e}")
        json.dump({}, sys.stdout)


if __name__ == "__main__":
    main()
