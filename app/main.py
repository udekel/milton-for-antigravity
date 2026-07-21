import json
import logging
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

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

logging.basicConfig(level=logging.INFO, format="[Milton Server] %(asctime)s - %(levelname)s - %(message)s")


class MiltonHTTPRequestHandler(BaseHTTPRequestHandler):

    def _send_json(self, data: dict, status_code: int = 200):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_OPTIONS(self):
        self._send_json({})

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path in ("/", "/api/v1/healthz"):
            self._send_json({"status": "ok", "app": settings.app_name})
            return

        store = get_session_store()

        # GET /api/v1/session/{session_id}/summary
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

        # GET /api/v1/session/{session_id}/explain-request
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
        parsed = urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception:
            body = {}

        store = get_session_store()

        # POST /api/v1/session/start
        if path == "/api/v1/session/start":
            sid = store.create_session(
                session_id=body.get("session_id"),
                workspace_paths=body.get("workspace_paths")
            )
            self._send_json({"session_id": sid, "status": "initialized"})
            return

        # POST /api/v1/session/{session_id}/fragment
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

        # POST /api/v1/session/{session_id}/turn
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


def run_server(host: str = settings.host, port: int = settings.port):
    server = MiltonHTTPServer((host, port), MiltonHTTPRequestHandler)
    logging.info(f"🚀 Milton Agent Backend running locally on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Stopping Milton Server...")
        server.server_close()


if __name__ == "__main__":
    run_server()

