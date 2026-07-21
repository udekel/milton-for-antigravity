import json
import logging
import os
from enum import Enum
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="[Milton Plugin] %(asctime)s - %(levelname)s - %(message)s")


class MiltonMode(str, Enum):
    OFF = "OFF"
    SUMMARIZE_EVERYTHING = "SUMMARIZE_EVERYTHING"
    ONLY_EXPLAIN_REQUESTS = "ONLY_EXPLAIN_REQUESTS"


class MiltonAntigravityPlugin:
    """Milton plugin for Antigravity/Jetski harness.
    
    Exfiltrates turn prompts, raw mutterings, and tool calls,
    and intervenes by injecting summary placeholders into the agent trajectory.
    """

    def __init__(self, mode: MiltonMode = MiltonMode.SUMMARIZE_EVERYTHING, api_url: str = "http://localhost:8000"):
        self.mode = mode
        self.api_url = api_url
        self.session_id: Optional[str] = None
        self.current_mutterings: List[Dict[str, Any]] = []

    def on_session_start(self, session_id: str, workspace_paths: List[str]):
        """Hook called when a new coding session starts."""
        self.session_id = session_id
        self.current_mutterings.clear()
        logging.info(f"Session started: {session_id} (Mode: {self.mode.value})")

    def on_user_prompt(self, prompt: str):
        """Hook called when user submits a prompt."""
        if self.mode == MiltonMode.OFF:
            return
        logging.info(f"Captured User Prompt: '{prompt}'")
        self._exfiltrate_fragment({"type": "user_prompt", "content": prompt})

    def on_muttering(self, thinking_content: str):
        """Hook called whenever intermediate thought / stream of thought occurs."""
        if self.mode == MiltonMode.OFF:
            return
        logging.info(f"Exfiltrating Muttering/Thought: '{thinking_content}'")
        fragment = {"type": "muttering", "content": thinking_content}
        self.current_mutterings.append(fragment)
        self._exfiltrate_fragment(fragment)

    def on_pre_tool_call(self, tool_name: str, tool_args: Dict[str, Any], step_idx: int) -> Optional[Dict[str, Any]]:
        """Pre-tool execution hook. Intercepts tool usage and checks if permission request explanation is needed."""
        if self.mode == MiltonMode.OFF:
            return None

        logging.info(f"Captured Pre-Tool Call [Step {step_idx}]: {tool_name}({tool_args})")
        fragment = {
            "type": "pre_tool_call",
            "tool_name": tool_name,
            "args": tool_args,
            "step_idx": step_idx,
        }
        self.current_mutterings.append(fragment)
        self._exfiltrate_fragment(fragment)

        # Proof of concept intervention on sensitive/ask actions
        if self.mode in (MiltonMode.ONLY_EXPLAIN_REQUESTS, MiltonMode.SUMMARIZE_EVERYTHING):
            if tool_name in ("run_command", "ask_permission", "write_file"):
                explanation_placeholder = (
                    f"🔍 [Milton Request Rationale] Agent is attempting '{tool_name}'. "
                    f"Prior mutterings show it reasoned about running shell commands to check setup."
                )
                logging.info(f"Intervening with permission explanation placeholder!")
                return {
                    "decision": "ask",
                    "reason": explanation_placeholder,
                    "injected_message": explanation_placeholder
                }
        return None

    def on_post_tool_call(self, tool_name: str, tool_output: str, error: Optional[str] = None):
        """Post-tool execution hook."""
        if self.mode == MiltonMode.OFF:
            return

        logging.info(f"Captured Post-Tool Call Result for: {tool_name}")
        fragment = {
            "type": "post_tool_call",
            "tool_name": tool_name,
            "error": error,
            "output_preview": tool_output[:100] if tool_output else None,
        }
        self.current_mutterings.append(fragment)
        self._exfiltrate_fragment(fragment)

    def on_turn_complete(self, final_response: str) -> Optional[str]:
        """Hook called when the agent finishes a turn."""
        if self.mode == MiltonMode.OFF:
            return None

        logging.info("Turn completed. Generating mutterings summary...")

        if self.mode == MiltonMode.SUMMARIZE_EVERYTHING:
            summary_placeholder = self._generate_summary_placeholder(final_response)
            logging.info("Intervening with complete turn summary placeholder!")
            return summary_placeholder
        
        return None

    def _exfiltrate_fragment(self, fragment: Dict[str, Any]):
        """Simulates API transmission (ProcessFragment) to Milton backend."""
        pass

    def _generate_summary_placeholder(self, final_response: str) -> str:
        """Generates a structured summary placeholder from collected mutterings."""
        muttering_count = len([m for m in self.current_mutterings if m["type"] == "muttering"])
        tool_count = len([m for m in self.current_mutterings if m["type"] == "pre_tool_call"])

        return (
            "\n" + "="*65 + "\n"
            "📌 [MILTON MUTTERINGS SUMMARY]\n"
            f"  • Stream of Thought Steps Captured: {muttering_count}\n"
            f"  • Tool Invocation Steps Captured:   {tool_count}\n"
            "  • Rationale & Trajectory: Analyzed workspace files, validated environment.\n"
            "  • Dangerous Actions / Safety Flags: None detected.\n"
            f"  • Final Output Rationale: Finished requested operation successfully.\n"
            + "="*65 + "\n"
        )
