import json
import logging
from typing import Any, Dict, List, Optional

from app.config import settings
from app.models.schemas import ExplainRequestResult, FragmentData, TurnData

logger = logging.getLogger("milton.explainer")


class RequestExplainerAgent:
    """Permission Request Explainer Agent.
    
    Translates preceding stream-of-thought mutterings into a concise, human-readable rationale
    for why a specific permission or input request is needed.
    """

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or settings.gemini_api_key
        self.model_name = model_name or settings.gemini_model

    def explain(
        self,
        session_id: str,
        target_tool: str,
        turns: List[TurnData],
        fragments: List[FragmentData],
        tool_args: Optional[Dict[str, Any]] = None
    ) -> ExplainRequestResult:
        if self.api_key:
            try:
                return self._explain_with_gemini(session_id, target_tool, turns, fragments, tool_args)
            except Exception as e:
                logger.warning(f"Gemini API call failed: {e}. Falling back to local heuristic explainer.")

        return self._explain_heuristic(session_id, target_tool, turns, fragments, tool_args)

    def _explain_heuristic(
        self,
        session_id: str,
        target_tool: str,
        turns: List[TurnData],
        fragments: List[FragmentData],
        tool_args: Optional[Dict[str, Any]] = None
    ) -> ExplainRequestResult:
        all_fragments = list(fragments)
        for t in turns:
            all_fragments.extend(t.fragments)

        recent_thoughts = []
        for frag in reversed(all_fragments[-10:]):
            if frag.content:
                recent_thoughts.append(frag.content.strip())

        context_summary = (
            f"Preceding trajectory contains {len(turns)} turns and {len(all_fragments)} events. "
            f"Latest focus: '{recent_thoughts[0]}' " if recent_thoughts else "Initial turn action."
        )

        args_str = f" with args {tool_args}" if tool_args else ""

        if target_tool == "run_command":
            risk_level = "medium"
            explanation = (
                f"The agent wants to execute shell command ({target_tool}{args_str}). "
                f"Based on recent thoughts ('{recent_thoughts[0] if recent_thoughts else 'environment check'}'), "
                f"it needs shell access to run diagnostics or tests."
            )
        elif target_tool in ("write_file", "delete_file"):
            risk_level = "high" if target_tool == "delete_file" else "medium"
            explanation = (
                f"The agent wants to modify filesystem resources ({target_tool}{args_str}). "
                f"Preceding mutterings show it reasoned about creating or editing code files."
            )
        else:
            risk_level = "low"
            explanation = (
                f"The agent requires access to tool '{target_tool}'{args_str}. "
                f"Preceding reasoning steps indicate it needs this tool to fulfill your prompt."
            )

        return ExplainRequestResult(
            session_id=session_id,
            target_tool=target_tool,
            explanation=explanation,
            risk_level=risk_level,
            preceding_context_summary=context_summary
        )

    def _explain_with_gemini(
        self,
        session_id: str,
        target_tool: str,
        turns: List[TurnData],
        fragments: List[FragmentData],
        tool_args: Optional[Dict[str, Any]] = None
    ) -> ExplainRequestResult:
        from google import genai

        client = genai.Client(api_key=self.api_key)
        
        prompt = (
            "You are Milton. Explain why a coding agent is making this permission request.\n"
            f"Target Tool: {target_tool}\n"
            f"Tool Arguments: {tool_args}\n"
            f"Preceding Turns: {[t.to_dict() for t in turns[-3:]]}\n"
            f"Preceding Fragments: {[f.to_dict() for f in fragments[-10:]]}\n\n"
            "Return JSON matching keys: session_id, target_tool, explanation, risk_level, preceding_context_summary."
        )

        response = client.models.generate_content(
            model=self.model_name,
            contents=prompt,
        )

        data = json.loads(response.text)
        data["session_id"] = session_id
        data["target_tool"] = target_tool
        return ExplainRequestResult(**data)
