#!/usr/bin/env python3
"""Milton JSON Hook Executor for Jetski / Antigravity harness.

This script is invoked directly by Jetski via hooks.json.
It receives JSON arguments on stdin and outputs JSON hook results on stdout.
"""

import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

LOG_FILE = "/tmp/milton_hook.log"


def log_event(msg: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass


def read_transcript_mutterings(transcript_path: str) -> List[Dict[str, Any]]:
    """Reads the current conversation transcript JSONL file to extract model thoughts and actions."""
    if not transcript_path or not os.path.exists(transcript_path):
        log_event(f"Transcript path not found or invalid: {transcript_path}")
        return []

    mutterings = []
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("type") in ("PLANNER_RESPONSE", "MODEL"):
                        content = entry.get("content", "")
                        tool_calls = entry.get("tool_calls", [])
                        mutterings.append({
                            "content": content,
                            "tool_calls": tool_calls,
                            "step_index": entry.get("step_index")
                        })
                except Exception:
                    continue
    except Exception as e:
        log_event(f"Error reading transcript: {e}")

    return mutterings


def generate_summary(payload: Dict[str, Any]) -> str:
    """Generates a Milton Mutterings Summary from current trajectory transcript."""
    transcript_path = payload.get("transcriptPath", "")
    mutterings = read_transcript_mutterings(transcript_path)

    recent_thoughts = []
    recent_tools = []

    for m in mutterings[-5:]:
        if m.get("content"):
            text = m["content"].strip()
            if len(text) > 120:
                text = text[:120] + "..."
            recent_thoughts.append(text)
        for tc in m.get("tool_calls", []):
            if isinstance(tc, dict):
                recent_tools.append(tc.get("name") or tc.get("type", "tool"))

    summary_text = (
        "\n" + "="*60 + "\n"
        "📌 [MILTON MUTTERINGS SUMMARY]\n"
        f"• Stream of Thought Turns Processed: {len(mutterings)}\n"
        f"• Actions Executed: {', '.join(set(recent_tools)) if recent_tools else 'General Reasoning (No tools)'}\n"
    )
    if recent_thoughts:
        summary_text += f"• Latest Monologue: \"{recent_thoughts[-1]}\"\n"
    else:
        summary_text += "• Latest Monologue: User turn initiated.\n"

    summary_text += "="*60 + "\n"
    return summary_text


def handle_pre_invocation(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Fires before model invocation. Injects summary as an ephemeral/user message."""
    log_event("Handling PreInvocation hook")
    summary_text = generate_summary(payload)

    return {
        "injectSteps": [
            {
                "userMessage": summary_text
            },
            {
                "ephemeralMessage": summary_text
            }
        ]
    }


def handle_post_invocation(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Fires after model invocation completes. Injects summary and sets termination behavior."""
    log_event("Handling PostInvocation hook")
    summary_text = generate_summary(payload)

    return {
        "injectSteps": [
            {
                "userMessage": summary_text
            },
            {
                "ephemeralMessage": summary_text
            }
        ],
        "terminationBehavior": ""
    }


def handle_pre_tool_use(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Fires before a tool executes."""
    tool_call = payload.get("toolCall", {})
    tool_name = tool_call.get("name", "")
    log_event(f"Handling PreToolUse hook for tool: {tool_name}")

    if tool_name in ("run_command", "write_file", "ask_permission"):
        return {
            "allowTool": True,
            "reason": f"🔍 [Milton Request Rationale] Tool '{tool_name}' requested. Preceding mutterings analyzed for safety."
        }

    return {"allowTool": True}


def handle_stop(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Fires when turn execution loop terminates."""
    log_event("Handling Stop hook")
    # Return normal stop allow
    return {}


def main():
    try:
        input_data = sys.stdin.read()
        log_event(f"Milton Hook Called with stdin length {len(input_data)}")
        
        if not input_data:
            json.dump({}, sys.stdout)
            return

        payload = json.loads(input_data)
        
        if "toolCall" in payload:
            result = handle_pre_tool_use(payload)
        elif "executionNum" in payload or "terminationReason" in payload:
            result = handle_stop(payload)
        elif "invocationNum" in payload and payload.get("invocationNum", 0) > 0:
            result = handle_post_invocation(payload)
        else:
            result = handle_pre_invocation(payload)

        json.dump(result, sys.stdout)
        sys.stdout.flush()
    except Exception as e:
        log_event(f"Exception in main: {e}")
        json.dump({}, sys.stdout)


if __name__ == "__main__":
    main()
