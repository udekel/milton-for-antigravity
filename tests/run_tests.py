#!/usr/bin/env python3
"""Native Python Unittest Test Suite for Milton Agent Backend."""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from datetime import datetime
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
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
from app.memory.session_store import SessionStore, get_session_store
from app.agents.analyzer import MutteringAnalyzerAgent
from app.agents.explainer import RequestExplainerAgent
from app.main import MiltonHTTPRequestHandler, HTTPServer


class TestSessionStore(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.temp_db.name
        self.temp_db.close()
        self.store = SessionStore(db_path=self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_create_session(self):
        sid = self.store.create_session(workspace_paths=["/tmp/workspace"])
        self.assertTrue(sid.startswith("session-"))

    def test_add_fragment(self):
        sid = self.store.create_session()
        frag = FragmentData(type="muttering", content="Analyzing code files...")
        frag_id = self.store.add_fragment(sid, frag)

        self.assertTrue(frag_id.startswith("frag-"))
        frags = self.store.get_fragments(sid)
        self.assertEqual(len(frags), 1)
        self.assertEqual(frags[0].content, "Analyzing code files...")

    def test_add_turn_batch(self):
        sid = self.store.create_session()
        turns = [
            TurnData(
                user_prompt="Run build",
                current_action="run_command",
                final_response="Build succeeded.",
                fragments=[FragmentData(type="muttering", content="Running make...")]
            ),
            TurnData(
                user_prompt="Run tests",
                current_action="run_command",
                final_response="Tests passed.",
                fragments=[FragmentData(type="muttering", content="Running pytest...")]
            )
        ]

        processed = self.store.add_turn_batch(sid, turns)
        self.assertEqual(processed, 2)

        stored_turns = self.store.get_turns(sid)
        self.assertEqual(len(stored_turns), 2)
        self.assertEqual(stored_turns[0].user_prompt, "Run build")
        self.assertEqual(stored_turns[1].user_prompt, "Run tests")


class TestAgents(unittest.TestCase):

    def test_analyzer_agent(self):
        analyzer = MutteringAnalyzerAgent(api_key=None)
        fragments = [
            FragmentData(type="muttering", content="Searching for config.json..."),
            FragmentData(type="pre_tool_call", tool_name="run_command", args={"CommandLine": "find . -name config.json"}),
            FragmentData(type="muttering", content="Search failed due to permission error.")
        ]
        turns = [
            TurnData(user_prompt="Find config", fragments=fragments)
        ]

        summary = analyzer.analyze("session-123", turns, fragments)
        self.assertEqual(summary.session_id, "session-123")
        self.assertIn("Executed tool: run_command", summary.actions_executed)
        self.assertTrue(summary.needs_info_or_permissions)
        self.assertTrue(len(summary.human_summary) > 0)

    def test_explainer_agent(self):
        explainer = RequestExplainerAgent(api_key=None)
        fragments = [
            FragmentData(type="muttering", content="Need to update dependency packages.")
        ]
        turns = [
            TurnData(user_prompt="Install dependencies", fragments=fragments)
        ]

        explanation = explainer.explain("session-123", "run_command", turns, fragments, {"CommandLine": "pip install -r requirements.txt"})
        self.assertEqual(explanation.session_id, "session-123")
        self.assertEqual(explanation.target_tool, "run_command")
        self.assertIn("run_command", explanation.explanation)
        self.assertIn(explanation.risk_level, ("low", "medium", "high"))


class TestLocalHTTPServer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 8765), MiltonHTTPRequestHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever)
        cls.server_thread.daemon = True
        cls.server_thread.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_healthz_endpoint(self):
        with urllib.request.urlopen("http://127.0.0.1:8765/api/v1/healthz") as response:
            self.assertEqual(response.status, 200)
            data = json.loads(response.read().decode())
            self.assertEqual(data["status"], "ok")

    def test_end_to_end_api_flow(self):
        # 1. Start Session
        req = urllib.request.Request("http://127.0.0.1:8765/api/v1/session/start", data=json.dumps({"workspace_paths": ["/tmp"]}).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            sid = data["session_id"]
            self.assertTrue(sid.startswith("session-"))

        # 2. Upload Fragment
        frag_payload = {
            "type": "pre_tool_call",
            "tool_name": "run_command",
            "args": {"CommandLine": "pytest"}
        }
        req_frag = urllib.request.Request(f"http://127.0.0.1:8765/api/v1/session/{sid}/fragment", data=json.dumps(frag_payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req_frag) as resp:
            data = json.loads(resp.read().decode())
            self.assertEqual(data["status"], "success")

        # 3. Upload Batched Turn
        turn_batch_payload = {
            "turns": [
                {
                    "user_prompt": "Run tests",
                    "current_action": "run_command",
                    "final_response": "Passed",
                    "fragments": [{"type": "muttering", "content": "Running test suite..."}]
                }
            ]
        }
        req_turn = urllib.request.Request(f"http://127.0.0.1:8765/api/v1/session/{sid}/turn", data=json.dumps(turn_batch_payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req_turn) as resp:
            data = json.loads(resp.read().decode())
            self.assertEqual(data["status"], "success")

        # 4. Get Summary
        with urllib.request.urlopen(f"http://127.0.0.1:8765/api/v1/session/{sid}/summary") as resp:
            data = json.loads(resp.read().decode())
            self.assertEqual(data["session_id"], sid)
            self.assertIn("Executed tool: run_command", data["actions_executed"])

        # 5. Explain Permission Request
        with urllib.request.urlopen(f"http://127.0.0.1:8765/api/v1/session/{sid}/explain-request?target_tool=run_command") as resp:
            data = json.loads(resp.read().decode())
            self.assertEqual(data["target_tool"], "run_command")
            self.assertIn("run_command", data["explanation"])


if __name__ == "__main__":
    unittest.main()
