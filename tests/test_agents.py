import pytest
from app.agents.analyzer import MutteringAnalyzerAgent
from app.agents.explainer import RequestExplainerAgent
from app.models.schemas import FragmentData, TurnData


def test_muttering_analyzer_heuristic():
    analyzer = MutteringAnalyzerAgent(api_key=None)
    fragments = [
        FragmentData(type="muttering", content="I need to inspect the build config."),
        FragmentData(type="pre_tool_call", tool_name="run_command", args={"CommandLine": "make build"}),
        FragmentData(type="muttering", content="Execution failed due to missing flag.")
    ]
    turns = [
        TurnData(user_prompt="Build project", fragments=fragments)
    ]

    result = analyzer.analyze("session-test", turns, fragments)
    assert result.session_id == "session-test"
    assert len(result.actions_executed) > 0
    assert "Executed tool: run_command" in result.actions_executed
    assert len(result.tested_and_rejected) > 0
    assert result.needs_info_or_permissions is True


def test_request_explainer_heuristic():
    explainer = RequestExplainerAgent(api_key=None)
    fragments = [
        FragmentData(type="muttering", content="Attempting to clean build directory.")
    ]
    turns = [
        TurnData(user_prompt="Clean project", fragments=fragments)
    ]

    result = explainer.explain("session-test", "run_command", turns, fragments, {"CommandLine": "rm -rf build"})
    assert result.session_id == "session-test"
    assert result.target_tool == "run_command"
    assert "run_command" in result.explanation
    assert result.risk_level in ("low", "medium", "high")
