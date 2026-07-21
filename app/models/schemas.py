from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class FragmentData:
    type: str
    fragment_id: Optional[str] = None
    content: Optional[str] = None
    tool_name: Optional[str] = None
    args: Optional[Dict[str, Any]] = None
    step_idx: Optional[int] = None
    output_preview: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FragmentData":
        return cls(
            type=data.get("type", "muttering"),
            fragment_id=data.get("fragment_id"),
            content=data.get("content"),
            tool_name=data.get("tool_name"),
            args=data.get("args"),
            step_idx=data.get("step_idx"),
            output_preview=data.get("output_preview"),
            timestamp=data.get("timestamp") or datetime.utcnow().isoformat()
        )


@dataclass
class TurnData:
    user_prompt: str
    turn_id: Optional[str] = None
    fragments: List[FragmentData] = field(default_factory=list)
    current_action: Optional[str] = None
    final_response: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "user_prompt": self.user_prompt,
            "fragments": [f.to_dict() if hasattr(f, "to_dict") else f for f in self.fragments],
            "current_action": self.current_action,
            "final_response": self.final_response,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TurnData":
        frags = [FragmentData.from_dict(f) if isinstance(f, dict) else f for f in data.get("fragments", [])]
        return cls(
            user_prompt=data.get("user_prompt", ""),
            turn_id=data.get("turn_id"),
            fragments=frags,
            current_action=data.get("current_action"),
            final_response=data.get("final_response"),
            timestamp=data.get("timestamp") or datetime.utcnow().isoformat()
        )


@dataclass
class BatchTurnPayload:
    turns: List[TurnData] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"turns": [t.to_dict() for t in self.turns]}


@dataclass
class StartSessionRequest:
    session_id: Optional[str] = None
    workspace_paths: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StartSessionResponse:
    session_id: str
    status: str = "initialized"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProcessFragmentResponse:
    session_id: str
    fragment_id: str
    total_fragments_stored: int
    status: str = "success"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProcessTurnResponse:
    session_id: str
    turns_processed: int
    total_turns_stored: int
    status: str = "success"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SummaryResult:
    session_id: str
    human_summary: str
    actions_executed: List[str] = field(default_factory=list)
    tested_and_rejected: List[str] = field(default_factory=list)
    key_decisions: List[str] = field(default_factory=list)
    risk_flags: List[str] = field(default_factory=list)
    needs_info_or_permissions: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExplainRequestResult:
    session_id: str
    target_tool: str
    explanation: str
    preceding_context_summary: str
    risk_level: str = "low"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
