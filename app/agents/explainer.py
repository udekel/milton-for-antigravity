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
            if frag.content and frag.type in ("muttering", "user_prompt"):
                recent_thoughts.append(frag.content.strip())

        last_thought = recent_thoughts[0] if recent_thoughts else ""

        # Build explanation focusing on WHY the permission is needed (rationale/purpose)
        if last_thought:
            explanation = f"Needed to support ongoing action: {last_thought}"
        elif target_tool == "run_command":
            cmd = (tool_args or {}).get("CommandLine", "")
            if "test" in cmd or "pytest" in cmd:
                explanation = "Needed to run test suite and verify implementation."
            elif "build" in cmd or "make" in cmd:
                explanation = "Needed to compile project artifacts and verify build status."
            elif "git" in cmd:
                explanation = "Needed to check or update git repository status and commits."
            else:
                explanation = f"Needed to execute command '{cmd}' to complete task requirements." if cmd else "Needed to execute shell diagnostic or build command."
        elif target_tool in ("write_file", "replace_file_content", "multi_replace_file_content"):
            target_path = (tool_args or {}).get("TargetFile", "")
            file_name = target_path.split("/")[-1] if target_path else "workspace file"
            explanation = f"Needed to update {file_name} with required code changes."
        elif target_tool == "delete_file":
            explanation = "Needed to remove obsolete workspace files."
        else:
            explanation = f"Needed to execute action for tool '{target_tool}' to fulfill turn objective."

        # Risk assessment
        if target_tool in ("delete_file", "run_command"):
            risk_level = "medium"
        elif target_tool in ("write_file", "replace_file_content", "multi_replace_file_content"):
            risk_level = "medium"
        else:
            risk_level = "low"

        context_summary = (
            f"Preceding trajectory contains {len(turns)} turns and {len(all_fragments)} events. "
            f"Primary focus: {last_thought or 'Turn execution'}"
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
            "You are Milton. Explain EXCLUSIVELY WHY a coding agent needs this permission request based on its intermediate thoughts and goal.\n"
            "Do NOT restate what tool or arguments are being executed (the user already sees the tool request itself).\n"
            "Provide a concise plain text explanation without any markdown formatting, markup, emojis, brackets, or backticks.\n"
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

