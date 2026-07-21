import asyncio
import json
import logging
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

try:
    from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False
    BackgroundTasks = None
    FastAPI = None
    HTTPException = None
    Request = None

from app.agents.analyzer import MutteringAnalyzerAgent
from app.agents.explainer import RequestExplainerAgent
from app.config import settings
from app.memory.session_store import get_session_store
from app.models.schemas import (
    BatchTurnPayload,
    FragmentData,
    StartSessionRequest,
    TurnData,
)
from app.utils.logger import get_json_logger
from app.utils.tracing import (
    get_current_span_id,
    get_current_trace_id,
    get_trace_headers,
    parse_traceparent,
    set_trace_context,
)

logger = get_json_logger("milton.server")

# =====================================================================
# FASTAPI ASYNC APPLICATION (Advanced / Non-Blocking Mode)
# =====================================================================
if HAS_FASTAPI:
    fastapi_app = FastAPI(title=settings.app_name, version="1.0.0")

    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    class DummyFastAPI:
        def middleware(self, *args, **kwargs):
            return lambda fn: fn
        def get(self, *args, **kwargs):
            return lambda fn: fn
        def post(self, *args, **kwargs):
            return lambda fn: fn

    fastapi_app = DummyFastAPI()


@fastapi_app.middleware("http")
async def trace_middleware(request: Request, call_next):
    traceparent = request.headers.get("traceparent") or request.headers.get("X-Trace-ID")
    if traceparent:
        parsed = parse_traceparent(traceparent)
        if parsed:
            set_trace_context(parsed[0], parsed[1])
        else:
            set_trace_context(trace_id=traceparent if len(traceparent) == 32 else None)
    else:
        set_trace_context()

    response = await call_next(request)

    headers = get_trace_headers()
    for k, v in headers.items():
        response.headers[k] = v
    return response


@fastapi_app.get("/")
@fastapi_app.get("/api/v1/healthz")
async def healthz():
    logger.info("Health check processed", extra={"status_code": 200})
    return {"status": "ok", "app": settings.app_name, "server_mode": settings.server_mode}


@fastapi_app.post("/api/v1/session/start")
async def async_start_session(payload: Dict[str, Any]):
    store = get_session_store()
    sid = await store.async_create_session(
        session_id=payload.get("session_id"),
        workspace_paths=payload.get("workspace_paths")
    )
    return {"session_id": sid, "status": "initialized"}


def _background_process_fragment(session_id: str, frag: FragmentData):
    """Background task function to process and index fragments non-blockingly."""
    try:
        store = get_session_store()
        logger.info(f"Background processing fragment for session '{session_id}'", extra={"session_id": session_id})
        # Background precomputation or analysis can execute here asynchronously
    except Exception as e:
        logger.error(f"Error in background fragment processing: {e}")


@fastapi_app.post("/api/v1/session/{session_id}/fragment")
async def async_add_fragment(session_id: str, payload: Dict[str, Any], background_tasks: BackgroundTasks):
    store = get_session_store()
    frag = FragmentData.from_dict(payload)
    frag_id = await store.async_add_fragment(session_id, frag)
    total = len(await store.async_get_fragments(session_id))

    if settings.async_background_processing:
        background_tasks.add_task(_background_process_fragment, session_id, frag)

    return {
        "status": "success",
        "session_id": session_id,
        "fragment_id": frag_id,
        "total_fragments_stored": total
    }


def _background_process_turn_batch(session_id: str, turns: List[TurnData]):
    """Background task function to process and index turn batches non-blockingly."""
    try:
        store = get_session_store()
        logger.info(f"Background processing turn batch for session '{session_id}'", extra={"session_id": session_id})
    except Exception as e:
        logger.error(f"Error in background turn batch processing: {e}")


@fastapi_app.post("/api/v1/session/{session_id}/turn")
async def async_add_turn(session_id: str, payload: Dict[str, Any], background_tasks: BackgroundTasks):
    store = get_session_store()
    raw_turns = payload.get("turns", [])
    turns = [TurnData.from_dict(t) for t in raw_turns]
    processed = await store.async_add_turn_batch(session_id, turns)
    total = len(await store.async_get_turns(session_id))

    if settings.async_background_processing:
        background_tasks.add_task(_background_process_turn_batch, session_id, turns)

    return {
        "status": "success",
        "session_id": session_id,
        "turns_processed": processed,
        "total_turns_stored": total
    }


@fastapi_app.get("/api/v1/session/{session_id}/summary")
async def async_get_summary(session_id: str):
    store = get_session_store()
    turns = await store.async_get_turns(session_id)
    fragments = await store.async_get_fragments(session_id)
    if not turns and not fragments:
        raise HTTPException(status_code=404, detail=f"No data found for session {session_id}")

    analyzer = MutteringAnalyzerAgent()
    result = await asyncio.to_thread(analyzer.analyze, session_id, turns, fragments)
    return result.to_dict()


@fastapi_app.get("/api/v1/session/{session_id}/explain-request")
async def async_explain_request(session_id: str, target_tool: str = "run_command", tool_args: Optional[str] = None):
    store = get_session_store()
    parsed_args = None
    if tool_args:
        try:
            parsed_args = json.loads(tool_args)
        except Exception:
            parsed_args = {"raw": tool_args}

    turns = await store.async_get_turns(session_id)
    fragments = await store.async_get_fragments(session_id)

    explainer = RequestExplainerAgent()
    result = await asyncio.to_thread(explainer.explain, session_id, target_tool, turns, fragments, parsed_args)
    return result.to_dict()


# =====================================================================
# LEGACY SYNCHRONOUS HTTP HANDLER (Simple / Blocking Mode)
# =====================================================================
class MiltonHTTPRequestHandler(BaseHTTPRequestHandler):

    def _extract_trace_context(self):
        traceparent = self.headers.get("traceparent") or self.headers.get("X-Trace-ID")
        if traceparent:
            parsed = parse_traceparent(traceparent)
            if parsed:
                set_trace_context(parsed[0], parsed[1])
            else:
                set_trace_context(trace_id=traceparent if len(traceparent) == 32 else None)
        else:
            set_trace_context()

    def _send_json(self, data: dict, status_code: int = 200):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "*")
        self.send_header("Access-Control-Allow-Headers", "*")

        headers = get_trace_headers()
        for k, v in headers.items():
            self.send_header(k, v)

        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_OPTIONS(self):
        self._extract_trace_context()
        self._send_json({})

    def do_GET(self):
        self._extract_trace_context()
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path in ("/", "/api/v1/healthz"):
            logger.info("Health check processed", extra={"status_code": 200})
            self._send_json({"status": "ok", "app": settings.app_name, "server_mode": "sync"})
            return

        store = get_session_store()

        if path.startswith("/api/v1/session/") and path.endswith("/summary"):
            parts = path.split("/")
            session_id = parts[4]
            turns = store.get_turns(session_id)
            fragments = store.get_fragments(session_id)
            if not turns and not fragments:
                self._send_json({"error": f"No data found for session {session_id}"}, 404)
                return
            analyzer = MutteringAnalyzerAgent()
            result = analyzer.analyze(session_id, turns, fragments)
            self._send_json(result.to_dict())
            return

        if path.startswith("/api/v1/session/") and path.endswith("/explain-request"):
            parts = path.split("/")
            session_id = parts[4]
            target_tool = query.get("target_tool", ["run_command"])[0]
            tool_args_str = query.get("tool_args", [None])[0]
            parsed_args = None
            if tool_args_str:
                try:
                    parsed_args = json.loads(tool_args_str)
                except Exception:
                    parsed_args = {"raw": tool_args_str}

            turns = store.get_turns(session_id)
            fragments = store.get_fragments(session_id)
            explainer = RequestExplainerAgent()
            result = explainer.explain(session_id, target_tool, turns, fragments, parsed_args)
            self._send_json(result.to_dict())
            return

        self._send_json({"error": "Not Found"}, 404)

    def do_POST(self):
        self._extract_trace_context()
        parsed = urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception:
            body = {}

        store = get_session_store()

        if path == "/api/v1/session/start":
            sid = store.create_session(
                session_id=body.get("session_id"),
                workspace_paths=body.get("workspace_paths")
            )
            self._send_json({"session_id": sid, "status": "initialized"})
            return

        if path.startswith("/api/v1/session/") and path.endswith("/fragment"):
            parts = path.split("/")
            session_id = parts[4]
            frag = FragmentData.from_dict(body)
            frag_id = store.add_fragment(session_id, frag)
            total = len(store.get_fragments(session_id))
            self._send_json({
                "status": "success",
                "session_id": session_id,
                "fragment_id": frag_id,
                "total_fragments_stored": total
            })
            return

        if path.startswith("/api/v1/session/") and path.endswith("/turn"):
            parts = path.split("/")
            session_id = parts[4]
            raw_turns = body.get("turns", [])
            turns = [TurnData.from_dict(t) for t in raw_turns]
            processed = store.add_turn_batch(session_id, turns)
            total = len(store.get_turns(session_id))
            self._send_json({
                "status": "success",
                "session_id": session_id,
                "turns_processed": processed,
                "total_turns_stored": total
            })
            return

        self._send_json({"error": "Not Found"}, 404)


class MiltonHTTPServer(HTTPServer):
    allow_reuse_address = True


def run_server(host: str = settings.host, port: int = settings.port, mode: Optional[str] = None):
    server_mode = mode or settings.server_mode
    if server_mode == "fastapi" and HAS_FASTAPI:
        import uvicorn
        logger.info(f"🚀 Milton Agent Backend running (FastAPI Async Mode) on http://{host}:{port}")
        uvicorn.run(fastapi_app, host=host, port=port, log_level="info")
    else:
        logger.info(f"🚀 Milton Agent Backend running (Sync HTTP Mode) on http://{host}:{port}")
        server = MiltonHTTPServer((host, port), MiltonHTTPRequestHandler)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logger.info("Stopping Milton Server...")
            server.server_close()


if __name__ == "__main__":
    run_server()
