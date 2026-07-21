"""Permission Request Explainer Agent module for generating concise human-readable tool rationale."""

import json
import logging
from typing import Any, Dict, List, Optional

from app.agents.orchestrator import MiltonOrchestrator
from app.config import settings
from app.models.schemas import ExplainRequestResult, FragmentData, TurnData
from app.router.model_router import ModelRouter
from app.utils.logger import get_json_logger
from app.utils.pii_redactor import PIIRedactor

logger = get_json_logger("milton.explainer")


class RequestExplainerAgent:
    """Permission Request Explainer Agent powered by MiltonOrchestrator supervisor.

    Generates concise (1-3 sentence) rationale explanations for permission-gated
    tool executions by analyzing user prompts and model mutterings.
    """

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        """Initializes the RequestExplainerAgent.

        Args:
            api_key: Optional API key override for Gemini model calls.
            model_name: Optional Gemini model tier identifier.
        """
        self.api_key = api_key or settings.gemini_api_key
        self.model_name = model_name or settings.gemini_model
        self.orchestrator = MiltonOrchestrator()

    def explain(
        self,
        session_id: str,
        target_tool: str,
        turns: List[TurnData],
        fragments: List[FragmentData],
        tool_args: Optional[Dict[str, Any]] = None
    ) -> ExplainRequestResult:
        """Generates a concise 1-3 sentence rationale explanation for a tool request.

        Args:
            session_id: Unique identifier for the active agent session.
            target_tool: Name of the target tool being executed (e.g. 'run_command').
            turns: Historical turns containing user prompts and executed tool calls.
            fragments: Real-time stream of thought mutterings and intermediate events.
            tool_args: Optional parameters and arguments passed to the target tool.

        Returns:
            ExplainRequestResult containing structured explanation, risk level, and summary context.

        Raises:
            ValueError: If session_id or target_tool parameters are missing.
        """
        if not session_id or not target_tool:
            raise ValueError("session_id and target_tool are required parameters.")

        selected_model = ModelRouter.route_explain_request(target_tool, tool_args, len(fragments))
        logger.info(
            f"RequestExplainerAgent routing request via ModelRouter: '{selected_model}'",
            extra={"session_id": session_id, "tool_name": target_tool}
        )

        # Delegate via Multi-Agent Orchestrator
        orch_res = self.orchestrator.orchestrate_pre_tool_explanation(
            session_id, target_tool, turns, fragments, tool_args
        )

        return ExplainRequestResult(
            session_id=session_id,
            target_tool=target_tool,
            explanation=orch_res.explanation_text,
            preceding_context_summary=orch_res.summary_text,
            risk_level=orch_res.risk.risk_level
        )

    def _explain_heuristic(
        self,
        session_id: str,
        target_tool: str,
        turns: List[TurnData],
        fragments: List[FragmentData],
        tool_args: Optional[Dict[str, Any]] = None
    ) -> ExplainRequestResult:
        """Fallback heuristic generator used when offline or during LLM error recovery.

        Args:
            session_id: Active session identifier.
            target_tool: Name of tool invocation.
            turns: Historical turn objects.
            fragments: Real-time mutterings.
            tool_args: Parameters passed to target tool.

        Returns:
            ExplainRequestResult with heuristic rationale and risk classification.
        """
        all_fragments = list(fragments)
        for t in turns:
            all_fragments.extend(t.fragments)

        recent_thoughts = []
        for frag in reversed(all_fragments[-10:]):
            if frag.content and frag.type in ("muttering", "user_prompt"):
                recent_thoughts.append(frag.content.strip())

        clean_thought = ""
        if recent_thoughts:
            t = recent_thoughts[0].replace("\n", " ").strip()
            if len(t) > 180:
                t = t[:177] + "..."
            clean_thought = t

        if clean_thought and not clean_thought.endswith("."):
            clean_thought += "."

        if target_tool == "run_command":
            cmd = (tool_args or {}).get("CommandLine", "")
            cmd_desc = f"Executing shell command `{cmd[:80]}`." if cmd else "Executing shell command."
            explanation = f"{clean_thought} {cmd_desc}".strip() if clean_thought else cmd_desc
        elif target_tool in ("write_file", "replace_file_content", "multi_replace_file_content", "write_to_file"):
            target_path = (tool_args or {}).get("TargetFile", "")
            file_name = target_path.split("/")[-1] if target_path else "workspace file"
            mod_desc = f"Applying code modifications to {file_name}."
            explanation = f"{clean_thought} {mod_desc}".strip() if clean_thought else mod_desc
        else:
            tool_desc = f"Executing tool '{target_tool}'."
            explanation = f"{clean_thought} {tool_desc}".strip() if clean_thought else tool_desc

        if target_tool in ("delete_file", "run_command"):
            risk_level = "HIGH"
        elif target_tool in ("write_file", "replace_file_content", "multi_replace_file_content"):
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        context_summary = (
            f"Preceding trajectory contains {len(turns)} turns and {len(all_fragments)} events. "
            f"Primary focus: {clean_thought or 'Turn execution'}"
        )

        return ExplainRequestResult(
            session_id=session_id,
            target_tool=target_tool,
            explanation=PIIRedactor.redact_text(explanation),
            risk_level=risk_level,
            preceding_context_summary=PIIRedactor.redact_text(context_summary)
        )

    def _explain_with_gemini(
        self,
        session_id: str,
        target_tool: str,
        turns: List[TurnData],
        fragments: List[FragmentData],
        tool_args: Optional[Dict[str, Any]] = None
    ) -> ExplainRequestResult:
        """Executes LLM inference with explicit JSON schema constraints and guided error recovery.

        Args:
            session_id: Active session identifier.
            target_tool: Name of target tool being executed.
            turns: Historical turn objects.
            fragments: Real-time mutterings.
            tool_args: Parameters for tool execution.

        Returns:
            ExplainRequestResult produced by Gemini model under JSON schema constraints.
        """
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)

        prompt = (
            "You are Milton. Explain EXCLUSIVELY WHY a coding agent needs this permission request based on its intermediate thoughts and goal.\n"
            "Do NOT restate what tool or arguments are being executed.\n"
            "Provide a concise 1-3 sentence explanation.\n\n"
            f"Target Tool: {target_tool}\n"
            f"Tool Arguments: {tool_args}\n"
            f"Preceding Turns: {[t.to_dict() for t in turns[-3:]]}\n"
            f"Preceding Fragments: {[f.to_dict() for f in fragments[-10:]]}"
        )

        # Enforce explicit JSON schema constraint
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema={
                "type": "OBJECT",
                "properties": {
                    "explanation": {"type": "STRING", "description": "Concise 1-3 sentence rationale explanation"},
                    "risk_level": {"type": "STRING", "enum": ["LOW", "MEDIUM", "HIGH"]},
                    "preceding_context_summary": {"type": "STRING"}
                },
                "required": ["explanation", "risk_level", "preceding_context_summary"]
            }
        )

        return self._execute_with_error_recovery(
            client=client,
            model_name=self.model_name,
            prompt=prompt,
            config=config,
            session_id=session_id,
            target_tool=target_tool,
            turns=turns,
            fragments=fragments,
            tool_args=tool_args
        )

    def _execute_with_error_recovery(
        self,
        client: Any,
        model_name: str,
        prompt: str,
        config: Any,
        session_id: str,
        target_tool: str,
        turns: List[TurnData],
        fragments: List[FragmentData],
        tool_args: Optional[Dict[str, Any]]
    ) -> ExplainRequestResult:
        """Guided error recovery handler for LLM generation failures.

        Args:
            client: Gemini API client instance.
            model_name: Name of target model tier.
            prompt: Initial LLM prompt.
            config: Generation config with JSON schema constraints.
            session_id: Active session ID.
            target_tool: Tool name.
            turns: Session turns.
            fragments: Session fragments.
            tool_args: Tool arguments.

        Returns:
            ExplainRequestResult from successful LLM generation or heuristic recovery.
        """
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config
            )
            data = json.loads(response.text)
            data["session_id"] = session_id
            data["target_tool"] = target_tool
            return ExplainRequestResult(**data)
        except Exception as initial_error:
            logger.warning(
                f"Initial LLM generation failed: {initial_error}. Executing guided error recovery...",
                extra={"session_id": session_id, "tool_name": target_tool}
            )
            # Guided recovery retry prompt with error context
            guided_prompt = (
                f"{prompt}\n\n"
                f"GUIDED ERROR RECOVERY NOTICE:\n"
                f"Your previous output failed with error: {initial_error}.\n"
                f"Re-generate valid JSON strictly adhering to schema keys: explanation, risk_level, preceding_context_summary."
            )
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=guided_prompt,
                    config=config
                )
                data = json.loads(response.text)
                data["session_id"] = session_id
                data["target_tool"] = target_tool
                return ExplainRequestResult(**data)
            except Exception as recovery_error:
                logger.error(
                    f"Guided error recovery failed: {recovery_error}. Falling back to local heuristic rationale.",
                    extra={"session_id": session_id, "tool_name": target_tool}
                )
                return self._explain_heuristic(session_id, target_tool, turns, fragments, tool_args)
