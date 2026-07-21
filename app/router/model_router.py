from enum import Enum
from typing import Any, Dict, Optional


class ModelTier(str, Enum):
    FAST_LITE = "gemini-2.5-flash-lite"
    STANDARD = "gemini-2.5-flash"
    HIGH_REASONING = "gemini-2.5-pro"


class ModelRouter:
    """Strategic Model Router.
    
    Dynamically routes LLM requests across model tiers based on tool risk level,
    trajectory length, and required reasoning depth.
    """

    HIGH_RISK_TOOLS = {
        "run_command",
        "write_to_file",
        "replace_file_content",
        "multi_replace_file_content",
        "delete_file",
        "execute_script"
    }

    READ_ONLY_TOOLS = {
        "view_file",
        "list_dir",
        "find_by_name",
        "code_search",
        "moma_search"
    }

    @classmethod
    def route_explain_request(cls, target_tool: str, tool_args: Optional[Dict[str, Any]] = None, trajectory_length: int = 0) -> str:
        # High-risk operations or deep trajectories require high-reasoning Pro model
        if target_tool in cls.HIGH_RISK_TOOLS or trajectory_length > 8:
            return ModelTier.HIGH_REASONING.value

        # Lightweight read-only operations route to Fast Lite model
        if target_tool in cls.READ_ONLY_TOOLS and trajectory_length < 4:
            return ModelTier.FAST_LITE.value

        # Default standard tier
        return ModelTier.STANDARD.value

    @classmethod
    def route_analyzer_request(cls, num_turns: int, num_fragments: int) -> str:
        total_elements = num_turns + num_fragments
        if total_elements > 15:
            return ModelTier.HIGH_REASONING.value
        elif total_elements < 5:
            return ModelTier.FAST_LITE.value
        return ModelTier.STANDARD.value
