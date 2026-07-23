"""Multi-Agent Orchestrator module for strategic sub-agent delegation and trajectory synthesis."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.router.model_router import ModelRouter, ModelTier
from app.utils.logger import get_json_logger
from app.utils.pii_redactor import PIIRedactor

logger = get_json_logger("milton.orchestrator")


@dataclass
class TrajectorySynthesis:
    """Dataclass holding synthesized trajectory goals and subtask objectives."""

    overall_goal: str
    current_subtask: str
    pending_tool_intent: str
    selected_model: str


@dataclass
class RiskAssessment:
    """Dataclass holding risk classification and safety notes for tool invocation."""

    tool_name: str
    risk_level: str  # HIGH, MEDIUM, LOW
    safety_notes: str
    selected_model: str


@dataclass
class OrchestratedResult:
    """Dataclass holding multi-agent orchestration results."""

    session_id: str
    summary_text: str
    explanation_text: str
    synthesis: TrajectorySynthesis
    risk: RiskAssessment
    selected_models: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Converts OrchestratedResult to dictionary format.

        Returns:
            Dictionary mapping of orchestration result attributes.
        """
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
        """Synthesizes stream of thought mutterings into structured subtasks and overall goals.

        Args:
            session_id: Active session identifier.
            turns: Historical turn objects.
            fragments: Real-time event fragments.

        Returns:
            TrajectorySynthesis object detailing active goals and subtasks.

        Raises:
            ValueError: If session_id is empty.
        """
        if not session_id:
            raise ValueError("session_id is a required parameter.")

        selected_model = ModelRouter.route_analyzer_request(len(turns), len(fragments))
        logger.info(
            f"TrajectorySynthesizer processing session '{session_id}' using model '{selected_model}'",
            extra={"session_id": session_id}
        )

        mutterings = []
        for f in fragments:
            if getattr(f, "type", None) == "muttering" and getattr(f, "content", None):
                mutterings.append(f.content)
            elif isinstance(f, dict) and f.get("type") == "muttering" and f.get("content"):
                mutterings.append(f["content"])

        last_thought = ""
        if mutterings:
            last_thought = mutterings[-1].strip().replace("\n", " ")
            if "The user says:" in last_thought:
                last_thought = last_thought.split("The user says:")[-1].strip()
            if len(last_thought) > 150:
                last_thought = last_thought[:147] + "..."

        last_thought = PIIRedactor.redact_text(last_thought)

        return TrajectorySynthesis(
            overall_goal=last_thought or "Executing workspace objective",
            current_subtask=last_thought or "Processing objective step",
            pending_tool_intent="Executing tool step",
            selected_model=selected_model
        )


class RiskAssessmentAgent:
    """Worker Agent: Evaluates safety & risk profile of target tool invocation."""

    def assess_risk(self, target_tool: str, tool_args: Optional[Dict[str, Any]] = None) -> RiskAssessment:
        """Assesses risk classification level (HIGH, MEDIUM, LOW) for a target tool invocation.

        Args:
            target_tool: Name of the target tool being executed.
            tool_args: Optional parameters passed to the tool.

        Returns:
            RiskAssessment object containing risk classification and safety notes.

        Raises:
            ValueError: If target_tool is empty.
        """
        if not target_tool:
            raise ValueError("target_tool is a required parameter.")

        selected_model = ModelRouter.route_explain_request(target_tool, tool_args, trajectory_length=5)
        logger.info(
            f"RiskAssessment processing tool '{target_tool}' using model '{selected_model}'",
            extra={"tool_name": target_tool}
        )

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
        """Initializes MiltonOrchestrator supervisor with TrajectorySynthesizer and RiskAssessor."""
        self.synthesizer = TrajectorySynthesizerAgent()
        self.risk_assessor = RiskAssessmentAgent()

    def orchestrate_pre_tool_explanation(
        self,
        session_id: str,
        target_tool: str,
        turns: List[Any],
        fragments: List[Any],
        tool_args: Optional[Dict[str, Any]] = None
    ) -> OrchestratedResult:
        """Delegates sub-tasks to TrajectorySynthesizer and RiskAssessor worker agents.

        Args:
            session_id: Active session identifier.
            target_tool: Name of target tool request.
            turns: Session turns history.
            fragments: Real-time mutterings stream.
            tool_args: Tool parameters.

        Returns:
            OrchestratedResult combining trajectory goals, risk assessment, and rationale text.

        Raises:
            ValueError: If session_id or target_tool is missing.
        """
        if not session_id or not target_tool:
            raise ValueError("session_id and target_tool are required parameters.")

        logger.info(
            f"MiltonOrchestrator delegating sub-agents for session '{session_id}' and tool '{target_tool}'",
            extra={"session_id": session_id, "tool_name": target_tool}
        )

        synthesis = self.synthesizer.synthesize(session_id, turns, fragments)
        risk = self.risk_assessor.assess_risk(target_tool, tool_args)

        selected_model = ModelRouter.route_explain_request(target_tool, tool_args, len(fragments))

        subtask = synthesis.current_subtask.strip()

        # Format Action X in laymen terms
        args = tool_args or {}
        if target_tool == "run_command":
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
        elif target_tool in ("write_file", "write_to_file", "replace_file_content", "multi_replace_file_content"):
            target_path = args.get("TargetFile", "")
            file_name = target_path.split("/")[-1] if target_path else "workspace file"
            action = f"modify file '{file_name}'"
        elif target_tool in ("read_url", "execute_url"):
            url = args.get("Url", "")
            domain = url.split("//")[-1].split("/")[0] if url else ""
            action = f"fetch remote page from '{domain}'" if domain else "access remote URL"
        elif target_tool == "delete_file":
            action = "remove a workspace file"
        else:
            action = f"execute tool '{target_tool}'"

        # Format Purpose Y in laymen terms
        if subtask:
            t = subtask
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

        explanation_text = f"The agent needs to {action} in order to {purpose}."
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
