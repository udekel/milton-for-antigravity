from datetime import datetime
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Query

from app.agents import MutteringAnalyzerAgent, RequestExplainerAgent
from app.memory import get_session_store
from app.models.schemas import (
    BatchTurnPayload,
    ExplainRequestResult,
    FragmentData,
    ProcessFragmentResponse,
    ProcessTurnResponse,
    StartSessionRequest,
    StartSessionResponse,
    SummaryResult,
    TurnData,
)

router = APIRouter(prefix="/api/v1")


@router.get("/healthz", tags=["Health"])
def health_check():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@router.post("/session/start", response_model=StartSessionResponse, tags=["Session"])
def start_session(request: Optional[StartSessionRequest] = None):
    store = get_session_store()
    req = request or StartSessionRequest()
    session_id = store.create_session(session_id=req.session_id, workspace_paths=req.workspace_paths)
    return StartSessionResponse(
        session_id=session_id,
        status="initialized",
        created_at=datetime.utcnow()
    )


@router.post("/session/{session_id}/turn", response_model=ProcessTurnResponse, tags=["Upload Stage"])
def process_turn(session_id: str, payload: BatchTurnPayload):
    """ProcessTurn (Batched): Uploads a batch of turns or turn events into session memory."""
    store = get_session_store()
    if not payload.turns:
        raise HTTPException(status_code=400, detail="Batch turns payload cannot be empty.")

    processed = store.add_turn_batch(session_id, payload.turns)
    total_turns = len(store.get_turns(session_id))

    return ProcessTurnResponse(
        status="success",
        session_id=session_id,
        turns_processed=processed,
        total_turns_stored=total_turns
    )


@router.post("/session/{session_id}/fragment", response_model=ProcessFragmentResponse, tags=["Upload Stage"])
def process_fragment(session_id: str, fragment: FragmentData):
    """ProcessFragment: Uploads a single real-time muttering or tool call fragment into session memory."""
    store = get_session_store()
    frag_id = store.add_fragment(session_id, fragment)
    total_frags = len(store.get_fragments(session_id))

    return ProcessFragmentResponse(
        status="success",
        session_id=session_id,
        fragment_id=frag_id,
        total_fragments_stored=total_frags
    )


@router.get("/session/{session_id}/summary", response_model=SummaryResult, tags=["Analysis Stage"])
def summarize_mutterings(session_id: str):
    """SummarizeMutterings: Returns a structured analysis of all session mutterings and actions."""
    store = get_session_store()
    turns = store.get_turns(session_id)
    fragments = store.get_fragments(session_id)

    if not turns and not fragments:
        raise HTTPException(status_code=404, detail=f"No trajectory data found for session {session_id}")

    analyzer = MutteringAnalyzerAgent()
    return analyzer.analyze(session_id, turns, fragments)


@router.get("/session/{session_id}/explain-request", response_model=ExplainRequestResult, tags=["Analysis Stage"])
def explain_user_request(
    session_id: str,
    target_tool: str = Query(..., description="Tool name, e.g. run_command or write_file"),
    tool_args: Optional[str] = Query(None, description="Optional serialized tool arguments")
):
    """ExplainUserRequest: Translates preceding mutterings into a human-readable permission request rationale."""
    store = get_session_store()
    turns = store.get_turns(session_id)
    fragments = store.get_fragments(session_id)

    if not turns and not fragments:
        raise HTTPException(status_code=404, detail=f"No trajectory data found for session {session_id}")

    parsed_args = None
    if tool_args:
        try:
            import json
            parsed_args = json.loads(tool_args)
        except Exception:
            parsed_args = {"raw": tool_args}

    explainer = RequestExplainerAgent()
    return explainer.explain(session_id, target_tool, turns, fragments, parsed_args)
