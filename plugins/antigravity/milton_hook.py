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

    # Format Action X in laymen terms
    args = tool_args or {}
    if tool_name == "run_command":
        cmd = (args.get("CommandLine") or "").strip()
        cmd_low = cmd.lower()
        if cmd_low.startswith("python") or "python3" in cmd_low:
            action = "run a python command"
        elif cmd_low.startswith("pytest"):
            action = "run a pytest test command"
        elif cmd_low.startswith("git"):
            action = "run a git version control command"
        elif cmd_low.startswith("gcloud"):
            action = "run a Google Cloud CLI command"
        elif cmd_low.startswith("make"):
            action = "run a build command"
        elif cmd_low.startswith("pip"):
            action = "run a package installation command"
        elif cmd:
            first_word = cmd.split()[0].split("/")[-1]
            action = f"run a '{first_word}' shell command"
        else:
            action = "run a shell command"
    elif tool_name in ("write_file", "write_to_file", "replace_file_content", "multi_replace_file_content"):
        target = args.get("TargetFile", "")
        fname = target.split("/")[-1] if target else "workspace file"
        action = f"modify file '{fname}'"
    elif tool_name in ("read_url", "execute_url"):
        url = args.get("Url", "")
        domain = url.split("//")[-1].split("/")[0] if url else ""
        action = f"fetch remote page from '{domain}'" if domain else "access remote URL"
    elif tool_name == "delete_file":
        action = "remove a workspace file"
    else:
        action = f"execute tool '{tool_name}'"

    # Format Purpose Y in laymen terms
    if thought_str:
        t = thought_str.strip().replace("\n", " ")
        prefixes = [
            "the user wants to", "the user requested", "the user says:",
            "i will", "i need to", "i am going to", "let's", "let me",
            "i want to", "we need to", "i am", "need to"
        ]
        for prefix in prefixes:
            if t.lower().startswith(prefix):
                t = t[len(prefix):].strip()
                break

        if t:
            t = t[0].lower() + t[1:]

        t = t.rstrip(".")
        words = t.split()
        if len(words) > 12:
            t = " ".join(words[:12])

        ing_map = {
            "analyzing": "analyze",
            "checking": "check",
            "updating": "update",
            "installing": "install",
            "running": "run",
            "modifying": "modify",
            "fetching": "fetch",
            "processing": "process",
            "executing": "execute",
            "verifying": "verify",
            "searching": "search",
            "inspecting": "inspect",
        }
        words = t.split()
        if words and words[0].lower() in ing_map:
            words[0] = ing_map[words[0].lower()]
            t = " ".join(words)

        if t.startswith("to "):
            purpose = t[3:]
        else:
            purpose = t
    else:
        purpose = "proceed with the active task"

    return f"The agent needs to {action} in order to {purpose}."


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
    """Fires BEFORE tool execution. Queries Milton server or local transcript for rationale and summary of mutterings."""
    tool_call = payload.get("toolCall", {})
    tool_name = tool_call.get("name", "unknown_tool")
    tool_args = tool_call.get("args", {})
    transcript_path = payload.get("transcriptPath", "")

    log_event(f"Handling PreToolUse for tool '{tool_name}' in session '{session_id}'")

    # Sync recent transcript fragments to local Milton server if present
    sync_transcript_to_milton_server(session_id, transcript_path)

    # Attempt to fetch explanation rationale from local Milton server
    encoded_tool = urllib.parse.quote(tool_name)
    encoded_args = urllib.parse.quote(json.dumps(tool_args))
    res = http_get(f"/api/v1/session/{session_id}/explain-request?target_tool={encoded_tool}&tool_args={encoded_args}")

    if res and "explanation" in res:
        rationale = res["explanation"]
    else:
        # Robust fallback: extract rationale locally from transcript or tool signature
        rationale = extract_mutterings_rationale_from_transcript(transcript_path, tool_name, tool_args)

    reason_text = f"[Milton Rationale]\n{rationale}"

    if tool_name in ("run_command", "read_url", "ask_permission", "execute_url"):
        decision = "ask"
    else:
        decision = "allow"

    return {
        "decision": decision,
        "reason": reason_text
    }


def handle_post_invocation(session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Fires at turn completion or post-tool execution. Fetches server-generated summary and injects into UI."""
    log_event(f"Handling PostInvocation/PostToolUse for session '{session_id}'")
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

        # PreToolUse has 'toolCall' and no 'toolResponse'
        if "toolCall" in payload and "toolResponse" not in payload:
            result = handle_pre_tool_use(session_id, payload)
        else:
            result = handle_post_invocation(session_id, payload)

        json.dump(result, sys.stdout)
        sys.stdout.flush()

    except Exception as e:
        log_event(f"Exception in main: {e}")
        json.dump({}, sys.stdout)






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
        else:
            result = handle_post_invocation(session_id, payload)

        json.dump(result, sys.stdout)
        sys.stdout.flush()

    except Exception as e:
        log_event(f"Exception in main: {e}")
        json.dump({}, sys.stdout)


if __name__ == "__main__":
    main()
