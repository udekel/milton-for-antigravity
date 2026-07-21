"""Muttering Analyzer Agent module for distilling intermediate LLM stream-of-thought mutterings."""

import json
import logging
from typing import Any, Dict, List, Optional

from app.agents.orchestrator import TrajectorySynthesizerAgent
from app.config import settings
from app.models.schemas import FragmentData, SummaryResult, TurnData
from app.router.model_router import ModelRouter
from app.utils.logger import get_json_logger
from app.utils.pii_redactor import PIIRedactor

logger = get_json_logger("milton.analyzer")


class MutteringAnalyzerAgent:
    """Muttering Analyzer Agent with strategic model routing.

    Processes stream-of-thought mutterings, tool invocations, and session turns
    to produce structured summary trajectories for human inspection.
    """

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        """Initializes the MutteringAnalyzerAgent.

        Args:
            api_key: Optional API key override for Gemini model calls.
            model_name: Optional Gemini model tier identifier.
        """
        self.api_key = api_key or settings.gemini_api_key
        self.model_name = model_name or settings.gemini_model
        self.synthesizer = TrajectorySynthesizerAgent()

    def analyze(self, session_id: str, turns: List[TurnData], fragments: List[FragmentData]) -> SummaryResult:
        """Analyzes multi-turn mutterings and events to generate a session trajectory summary.

        Args:
            session_id: Unique identifier for the active agent session.
            turns: List of historical turn objects containing prompts and tool events.
            fragments: List of real-time mutterings and event fragments.

        Returns:
            SummaryResult containing actions executed, rejected attempts, key decisions, and human summary.

        Raises:
            ValueError: If session_id is missing or empty.
        """
        if not session_id:
            raise ValueError("session_id is a required parameter for trajectory analysis.")

        selected_model = ModelRouter.route_analyzer_request(len(turns), len(fragments))
        logger.info(
            f"MutteringAnalyzerAgent routing request via ModelRouter: '{selected_model}'",
            extra={"session_id": session_id}
        )

        synthesis = self.synthesizer.synthesize(session_id, turns, fragments)
        res = self._analyze_heuristic(session_id, turns, fragments)
        res.human_summary = f"Summary of Mutterings: {synthesis.overall_goal} | Subtask: {synthesis.current_subtask}"
        return res

    def _analyze_heuristic(self, session_id: str, turns: List[TurnData], fragments: List[FragmentData]) -> SummaryResult:
        """Fallback heuristic trajectory analyzer.

        Args:
            session_id: Active session identifier.
            turns: Historical turn objects.
            fragments: Real-time mutterings.

        Returns:
            SummaryResult compiled via trajectory inspection.
        """
        actions_executed = []
        tested_and_rejected = []
        key_decisions = []
        risk_flags = []
        mutterings = []
        needs_permissions = False

        all_fragments = list(fragments)
        for t in turns:
            all_fragments.extend(t.fragments)

        for frag in all_fragments:
            text = (frag.content or "").lower()

            if frag.type == "muttering" and frag.content:
                mutterings.append(frag.content.strip())

            if frag.type == "pre_tool_call" and frag.tool_name:
                actions_executed.append(f"Executed tool: {frag.tool_name}")
                if frag.tool_name in ("run_command", "write_file", "ask_permission"):
                    needs_permissions = True
                    if frag.args:
                        risk_flags.append(f"Permission tool call: {frag.tool_name}")

            if "failed" in text or "error" in text or "rejected" in text or "cannot" in text:
                tested_and_rejected.append(frag.content[:100] if frag.content else "Sub-task failed/rejected")

            if "decided to" in text or "i will" in text or "need to" in text:
                key_decisions.append(frag.content[:100] if frag.content else "Agent decision step")

        if not actions_executed:
            actions_executed.append("Reasoned over prompt and trajectory history")

        if mutterings:
            recent_summary = " ".join(mutterings[-3:])
            if len(recent_summary) > 250:
                recent_summary = recent_summary[:247] + "..."
            human_summary = f"Summary of Mutterings: {recent_summary}"
        else:
            human_summary = (
                f"Summary of Mutterings: Processed {len(turns)} turns and {len(all_fragments)} events. "
                f"Executed {len(actions_executed)} tool actions."
            )

        return SummaryResult(
            session_id=session_id,
            actions_executed=list(set(actions_executed)),
            tested_and_rejected=list(set(tested_and_rejected)),
            key_decisions=list(set(key_decisions)),
            risk_flags=list(set(risk_flags)),
            needs_info_or_permissions=needs_permissions,
            human_summary=PIIRedactor.redact_text(human_summary)
        )

    def _analyze_with_gemini(self, session_id: str, turns: List[TurnData], fragments: List[FragmentData]) -> SummaryResult:
        """Executes LLM inference with explicit JSON schema constraints and guided error recovery.

        Args:
            session_id: Active session identifier.
            turns: Historical turn objects.
            fragments: Real-time mutterings.

        Returns:
            SummaryResult produced by Gemini model under JSON schema constraints.
        """
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)

        prompt = (
            "You are Milton, an AI system analyzing intermediate thoughts and tool calls from a coding agent.\n"
            "Provide a concise summary of the agent's stream-of-thought mutterings for human summary field.\n\n"
            f"Turns Data: {[t.to_dict() for t in turns]}\n"
            f"Fragments Data: {[f.to_dict() for f in fragments]}"
        )

        # Enforce explicit JSON schema constraint
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema={
                "type": "OBJECT",
                "properties": {
                    "actions_executed": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "tested_and_rejected": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "key_decisions": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "risk_flags": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "needs_info_or_permissions": {"type": "BOOLEAN"},
                    "human_summary": {"type": "STRING"}
                },
                "required": ["actions_executed", "tested_and_rejected", "key_decisions", "risk_flags", "needs_info_or_permissions", "human_summary"]
            }
        )

        return self._execute_with_error_recovery(
            client=client,
            model_name=self.model_name,
            prompt=prompt,
            config=config,
            session_id=session_id,
            turns=turns,
            fragments=fragments
        )

    def _execute_with_error_recovery(
        self,
        client: Any,
        model_name: str,
        prompt: str,
        config: Any,
        session_id: str,
        turns: List[TurnData],
        fragments: List[FragmentData]
    ) -> SummaryResult:
        """Guided error recovery handler for LLM trajectory analysis generation failures.

        Args:
            client: Gemini API client instance.
            model_name: Name of target model tier.
            prompt: Initial LLM prompt.
            config: Generation config with JSON schema constraints.
            session_id: Active session ID.
            turns: Session turns.
            fragments: Session fragments.

        Returns:
            SummaryResult from successful LLM generation or heuristic recovery.
        """
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config
            )
            data = json.loads(response.text)
            data["session_id"] = session_id
            return SummaryResult(**data)
        except Exception as initial_error:
            logger.warning(
                f"Initial trajectory analysis LLM generation failed: {initial_error}. Executing guided error recovery...",
                extra={"session_id": session_id}
            )
            guided_prompt = (
                f"{prompt}\n\n"
                f"GUIDED ERROR RECOVERY NOTICE:\n"
                f"Your previous output failed with error: {initial_error}.\n"
                f"Re-generate valid JSON strictly adhering to schema keys: actions_executed, tested_and_rejected, key_decisions, risk_flags, needs_info_or_permissions, human_summary."
            )
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=guided_prompt,
                    config=config
                )
                data = json.loads(response.text)
                data["session_id"] = session_id
                return SummaryResult(**data)
            except Exception as recovery_error:
                logger.error(
                    f"Guided error recovery failed: {recovery_error}. Falling back to local heuristic trajectory summary.",
                    extra={"session_id": session_id}
                )
                return self._analyze_heuristic(session_id, turns, fragments)
