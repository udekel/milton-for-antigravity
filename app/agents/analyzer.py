import json
import logging
from typing import Any, Dict, List, Optional

from app.config import settings
from app.models.schemas import FragmentData, SummaryResult, TurnData

logger = logging.getLogger("milton.analyzer")


class MutteringAnalyzerAgent:
    """Muttering Analyzer Agent.
    
    Parses and categorizes agent stream-of-thought, tool calls, and output trajectory.
    Uses Gemini API if available, with a deterministic heuristic fallback for offline local runs.
    """

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or settings.gemini_api_key
        self.model_name = model_name or settings.gemini_model

    def analyze(self, session_id: str, turns: List[TurnData], fragments: List[FragmentData]) -> SummaryResult:
        if self.api_key:
            try:
                return self._analyze_with_gemini(session_id, turns, fragments)
            except Exception as e:
                logger.warning(f"Gemini API call failed: {e}. Falling back to local heuristic analyzer.")

        return self._analyze_heuristic(session_id, turns, fragments)

    def _analyze_heuristic(self, session_id: str, turns: List[TurnData], fragments: List[FragmentData]) -> SummaryResult:
        actions_executed = []
        tested_and_rejected = []
        key_decisions = []
        risk_flags = []
        needs_permissions = False

        all_fragments = list(fragments)
        for t in turns:
            all_fragments.extend(t.fragments)

        for frag in all_fragments:
            text = (frag.content or "").lower()

            if frag.type == "pre_tool_call" and frag.tool_name:
                actions_executed.append(f"Executed tool: {frag.tool_name}")
                if frag.tool_name in ("run_command", "write_file", "ask_permission"):
                    needs_permissions = True
                    if frag.args:
                        risk_flags.append(f"Command execution: {frag.args}")

            if "failed" in text or "error" in text or "rejected" in text or "cannot" in text:
                tested_and_rejected.append(frag.content[:100] if frag.content else "Sub-task failed/rejected")

            if "decided to" in text or "i will" in text or "need to" in text:
                key_decisions.append(frag.content[:100] if frag.content else "Agent decision step")

        if not actions_executed:
            actions_executed.append("Reasoned over prompt and trajectory history")

        human_summary = (
            f"Processed {len(turns)} turns and {len(all_fragments)} fragments. "
            f"Executed {len(actions_executed)} tool actions with {len(risk_flags)} safety/risk flags."
        )

        return SummaryResult(
            session_id=session_id,
            actions_executed=list(set(actions_executed)),
            tested_and_rejected=list(set(tested_and_rejected)),
            key_decisions=list(set(key_decisions)),
            risk_flags=list(set(risk_flags)),
            needs_info_or_permissions=needs_permissions,
            human_summary=human_summary
        )

    def _analyze_with_gemini(self, session_id: str, turns: List[TurnData], fragments: List[FragmentData]) -> SummaryResult:
        from google import genai

        client = genai.Client(api_key=self.api_key)
        
        prompt = (
            "You are Milton, an AI system analyzing intermediate thoughts and tool calls from a coding agent.\n"
            "Analyze the provided trajectory data and return a JSON object with fields:\n"
            "- actions_executed (list of strings)\n"
            "- tested_and_rejected (list of strings)\n"
            "- key_decisions (list of strings)\n"
            "- risk_flags (list of strings)\n"
            "- needs_info_or_permissions (boolean)\n"
            "- human_summary (string)\n\n"
            f"Turns Data: {[t.to_dict() for t in turns]}\n"
            f"Fragments Data: {[f.to_dict() for f in fragments]}\n"
        )

        response = client.models.generate_content(
            model=self.model_name,
            contents=prompt,
        )

        data = json.loads(response.text)
        data["session_id"] = session_id
        return SummaryResult(**data)
