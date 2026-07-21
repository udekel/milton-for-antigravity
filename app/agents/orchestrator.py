from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.router.model_router import ModelRouter, ModelTier
from app.utils.logger import get_json_logger
from app.utils.pii_redactor import PIIRedactor

logger = get_json_logger("milton.orchestrator")


@dataclass
class TrajectorySynthesis:
    overall_goal: str
    current_subtask: str
    pending_tool_intent: str
    selected_model: str


@dataclass
class RiskAssessment:
    tool_name: str
    risk_level: str  # HIGH, MEDIUM, LOW
    safety_notes: str
    selected_model: str


@dataclass
class OrchestratedResult:
    session_id: str
    summary_text: str
    explanation_text: str
    synthesis: TrajectorySynthesis
    risk: RiskAssessment
    selected_models: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "summary_text": self.summary_text,
            "explanation_text": self.explanation_text,
            "synthesis": {
                "overall_goal": self.synthesis.overall_goal,
                "current_subtask": self.synthesis.current_subtask,
                "pending_tool_intent": self.synthesis.pending_tool_intent,
                "selected_model": self.synthesis.selected_model
            },
            "risk": {
                "tool_name": self.risk.tool_name,
                "risk_level": self.risk.risk_level,
                "safety_notes": self.risk.safety_notes,
                "selected_model": self.risk.selected_model
            },
            "selected_models": self.selected_models
        }


class TrajectorySynthesizerAgent:
    """Worker Agent: Synthesizes multi-turn stream-of-thought mutterings into structured goals."""

    def synthesize(self, session_id: str, turns: List[Any], fragments: List[Any]) -> TrajectorySynthesis:
        num_items = len(turns) + len(fragments)
        selected_model = ModelRouter.route_analyzer_request(len(turns), len(fragments))
        logger.info(f"TrajectorySynthesizer processing session '{session_id}' using model '{selected_model}'", extra={"session_id": session_id})

        # Extract recent thoughts
        mutterings = []
        for f in fragments:
            if getattr(f, "type", None) == "muttering" and getattr(f, "content", None):
                mutterings.append(f.content)
            elif isinstance(f, dict) and f.get("type") == "muttering" and f.get("content"):
                mutterings.append(f["content"])

        text_block = " ".join(mutterings[-5:]) if mutterings else "Analyzing session objective"
        text_block = PIIRedactor.redact_text(text_block)

        return TrajectorySynthesis(
            overall_goal=f"Execute user prompt strategy: {text_block[:100]}...",
            current_subtask=f"Synthesizing recent mutterings: {text_block[:80]}",
            pending_tool_intent="Preparing next tool step",
            selected_model=selected_model
        )


class RiskAssessmentAgent:
    """Worker Agent: Evaluates safety & risk profile of target tool invocation."""

    def assess_risk(self, target_tool: str, tool_args: Optional[Dict[str, Any]] = None) -> RiskAssessment:
        selected_model = ModelRouter.route_explain_request(target_tool, tool_args, trajectory_length=5)
        logger.info(f"RiskAssessment processing tool '{target_tool}' using model '{selected_model}'", extra={"tool_name": target_tool})

        tool_args = PIIRedactor.redact_data(tool_args or {})

        if target_tool in ModelRouter.HIGH_RISK_TOOLS:
            risk_level = "HIGH"
            safety_notes = f"Requires confirmation before mutating workspace or running command '{target_tool}'"
        elif target_tool in ModelRouter.READ_ONLY_TOOLS:
            risk_level = "LOW"
            safety_notes = f"Read-only workspace inspection via '{target_tool}'"
        else:
            risk_level = "MEDIUM"
            safety_notes = f"Standard action invocation for '{target_tool}'"

        return RiskAssessment(
            tool_name=target_tool,
            risk_level=risk_level,
            safety_notes=safety_notes,
            selected_model=selected_model
        )


class MiltonOrchestrator:
    """Supervisor Agent: Orchestrates multi-agent delegation and strategic model routing."""

    def __init__(self):
        self.synthesizer = TrajectorySynthesizerAgent()
        self.risk_assessor = RiskAssessmentAgent()

    def orchestrate_pre_tool_explanation(
        self, session_id: str, target_tool: str, turns: List[Any], fragments: List[Any], tool_args: Optional[Dict[str, Any]] = None
    ) -> OrchestratedResult:
        logger.info(f"MiltonOrchestrator delegating sub-agents for session '{session_id}' and tool '{target_tool}'", extra={"session_id": session_id, "tool_name": target_tool})

        # Delegate sub-tasks
        synthesis = self.synthesizer.synthesize(session_id, turns, fragments)
        risk = self.risk_assessor.assess_risk(target_tool, tool_args)

        selected_model = ModelRouter.route_explain_request(target_tool, tool_args, len(fragments))

        explanation_text = (
            f"Action in progress: {synthesis.current_subtask}. "
            f"Tool '{target_tool}' ({risk.risk_level} Risk) required. "
            f"Safety note: {risk.safety_notes}"
        )
        explanation_text = PIIRedactor.redact_text(explanation_text)

        summary_text = (
            f"Goal: {synthesis.overall_goal}\n"
            f"Intent: {synthesis.pending_tool_intent} using {target_tool}"
        )
        summary_text = PIIRedactor.redact_text(summary_text)

        selected_models = {
            "orchestrator": selected_model,
            "synthesizer": synthesis.selected_model,
            "risk_assessor": risk.selected_model
        }

        return OrchestratedResult(
            session_id=session_id,
            summary_text=summary_text,
            explanation_text=explanation_text,
            synthesis=synthesis,
            risk=risk,
            selected_models=selected_models
        )
