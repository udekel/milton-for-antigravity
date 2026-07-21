#!/usr/bin/env python3
"""Native Python Unittest Test Suite for Milton Agent Backend & Client Plugins."""

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
from app.router.model_router import ModelRouter, ModelTier
from app.agents.orchestrator import MiltonOrchestrator, TrajectorySynthesizerAgent, RiskAssessmentAgent
from app.utils.logger import JSONLogFormatter
from app.utils.pii_redactor import PIIRedactor
from app.utils.tracing import generate_trace_id, make_traceparent, parse_traceparent
from app.memory.session_store import SessionStore, get_session_store
from app.agents.analyzer import MutteringAnalyzerAgent
from app.agents.explainer import RequestExplainerAgent
from app.main import MiltonHTTPRequestHandler, HTTPServer
from plugins.antigravity.plugin import MiltonAntigravityPlugin, MiltonMode
from plugins.antigravity.milton_hook import handle_pre_tool_use, handle_post_invocation



class TestModelRouter(unittest.TestCase):

    def test_high_risk_tool_routing(self):
        tier = ModelRouter.route_explain_request("run_command", trajectory_length=2)
        self.assertEqual(tier, ModelTier.HIGH_REASONING.value)

    def test_read_only_tool_routing(self):
        tier = ModelRouter.route_explain_request("view_file", trajectory_length=1)
        self.assertEqual(tier, ModelTier.FAST_LITE.value)


class TestMiltonOrchestrator(unittest.TestCase):

    def test_orchestration_delegation(self):
        orchestrator = MiltonOrchestrator()
        result = orchestrator.orchestrate_pre_tool_explanation(
            session_id="test-session-123",
            target_tool="run_command",
            turns=[],
            fragments=[],
            tool_args={"CommandLine": "make test"}
        )
        self.assertEqual(result.risk.risk_level, "HIGH")
        self.assertIn("orchestrator", result.selected_models)
        self.assertIn("Executing", result.explanation_text)


class TestPIIRedactor(unittest.TestCase):


    def test_email_redaction(self):
        text = "Contact user at john.doe@example.com for support."
        redacted = PIIRedactor.redact_text(text)
        self.assertNotIn("john.doe@example.com", redacted)
        self.assertIn("[REDACTED_EMAIL]", redacted)

    def test_token_redaction(self):
        text = "Using secret=sample_dummy_token_abc_xyz for auth"
        redacted = PIIRedactor.redact_text(text)
        self.assertNotIn("sample_dummy_token_abc_xyz", redacted)
        self.assertIn("[REDACTED_SECRET]", redacted)




    def test_dict_secret_key_redaction(self):
        data = {"username": "udekel", "password": "supersecretpassword123", "nested": {"api_key": "abc123xyz456"}}
        redacted = PIIRedactor.redact_data(data)
        self.assertEqual(redacted["password"], "[REDACTED_SECRET]")
        self.assertEqual(redacted["nested"]["api_key"], "[REDACTED_SECRET]")


class TestTracingAndLogging(unittest.TestCase):

    def test_w3c_traceparent_parsing(self):
        header = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        parsed = parse_traceparent(header)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0], "4bf92f3577b34da6a3ce929d0e0e4736")
        self.assertEqual(parsed[1], "00f067aa0ba902b7")

    def test_json_log_formatter(self):
        import logging
        formatter = JSONLogFormatter()
        record = logging.LogRecord("test", logging.INFO, "path", 10, "User email is user@google.com", (), None)
        log_json_str = formatter.format(record)
        data = json.loads(log_json_str)
        self.assertEqual(data["level"], "INFO")
        self.assertIn("[REDACTED_EMAIL]", data["message"])
        self.assertIn("trace_id", data)


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
        # Ensure explanation explains WHY permission is needed in plain text
        self.assertIn("Executing", explanation.explanation)
        self.assertNotIn("🔍", explanation.explanation)
        self.assertNotIn("[Milton Server", explanation.explanation)
        self.assertIn(explanation.risk_level.lower(), ("low", "medium", "high"))



class TestLocalHTTPServerAndPlugins(unittest.TestCase):

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
            self.assertIn("Summary of Mutterings:", data["human_summary"])

        # 5. Explain Permission Request
        with urllib.request.urlopen(f"http://127.0.0.1:8765/api/v1/session/{sid}/explain-request?target_tool=run_command") as resp:
            data = json.loads(resp.read().decode())
            self.assertEqual(data["target_tool"], "run_command")
            self.assertIn("Executing", data["explanation"])


    def test_milton_plugin_client_http_communication(self):
        plugin = MiltonAntigravityPlugin(mode=MiltonMode.SUMMARIZE_EVERYTHING, api_url="http://127.0.0.1:8765")
        sid = f"session-plugin-test-{int(time.time())}"
        plugin.on_session_start(sid, ["/workspace"])

        plugin.on_user_prompt("Run test build")
        plugin.on_muttering("Analyzing build configuration...")

        intervention = plugin.on_pre_tool_call("run_command", {"CommandLine": "make"}, step_idx=1)
        self.assertIsNotNone(intervention)
        self.assertEqual(intervention["decision"], "ask")
        self.assertIn("[Milton Rationale", intervention["reason"])
        self.assertNotIn("🔍", intervention["reason"])


        plugin.on_post_tool_call("run_command", "Build OK")
        summary_banner = plugin.on_turn_complete("Build completed successfully.")
        self.assertIsNotNone(summary_banner)
        self.assertIn("[Milton Summary of Mutterings]", summary_banner)




class TestMiltonHook(unittest.TestCase):

    def test_handle_pre_tool_use_decision(self):
        payload = {
            "conversationId": "test-session-hook",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "whoami"}
            }
        }
        res = handle_pre_tool_use("test-session-hook", payload)
        self.assertEqual(res["decision"], "allow")
        self.assertIn("[Milton Rationale]", res["reason"])
        self.assertNotIn("Tool Target:", res["reason"])
        self.assertNotIn("Action in progress:", res["reason"])

    def test_milton_hook_main_silent_stderr(self):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        from plugins.antigravity.milton_hook import main as hook_main

        sample_input = json.dumps({
            "conversationId": "test-session-hook-main",
            "toolCall": {
                "name": "view_file",
                "args": {"AbsolutePath": "/tmp/test.txt"}
            }
        })

        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()

        original_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO(sample_input)
            with redirect_stdout(captured_stdout), redirect_stderr(captured_stderr):
                hook_main()
        finally:
            sys.stdin = original_stdin

        self.assertEqual(captured_stderr.getvalue(), "")
        output_json = json.loads(captured_stdout.getvalue())
        self.assertEqual(output_json["decision"], "allow")
        self.assertIn("[Milton Rationale]", output_json["reason"])


if __name__ == "__main__":
    unittest.main()
