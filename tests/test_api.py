import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.memory import get_session_store

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_store():
    store = get_session_store()
    store.clear_all()


def test_healthz():
    response = client.get("/api/v1/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_start_session():
    response = client.post("/api/v1/session/start", json={"workspace_paths": ["/tmp/test"]})
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert data["status"] == "initialized"


def test_process_fragment():
    # Start session
    s_res = client.post("/api/v1/session/start")
    sid = s_res.json()["session_id"]

    # Upload fragment
    frag_payload = {
        "type": "pre_tool_call",
        "tool_name": "run_command",
        "args": {"CommandLine": "pytest"},
        "step_idx": 1
    }
    response = client.post(f"/api/v1/session/{sid}/fragment", json=frag_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["total_fragments_stored"] == 1


def test_process_turn_batch():
    s_res = client.post("/api/v1/session/start")
    sid = s_res.json()["session_id"]

    turn_batch_payload = {
        "turns": [
            {
                "user_prompt": "Check environment",
                "current_action": "run_command",
                "final_response": "Environment OK",
                "fragments": [
                    {"type": "muttering", "content": "Checking python path..."}
                ]
            }
        ]
    }
    response = client.post(f"/api/v1/session/{sid}/turn", json=turn_batch_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["turns_processed"] == 1
    assert data["total_turns_stored"] == 1


def test_summarize_mutterings():
    s_res = client.post("/api/v1/session/start")
    sid = s_res.json()["session_id"]

    # Add data
    client.post(f"/api/v1/session/{sid}/fragment", json={"type": "muttering", "content": "Analyzing repository files"})
    client.post(f"/api/v1/session/{sid}/fragment", json={"type": "pre_tool_call", "tool_name": "run_command", "args": {"CommandLine": "ls -la"}})

    response = client.get(f"/api/v1/session/{sid}/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == sid
    assert len(data["actions_executed"]) > 0
    assert "Executed tool: run_command" in data["actions_executed"]


def test_explain_user_request():
    s_res = client.post("/api/v1/session/start")
    sid = s_res.json()["session_id"]

    client.post(f"/api/v1/session/{sid}/fragment", json={"type": "muttering", "content": "Need to check dependencies before running build"})

    response = client.get(f"/api/v1/session/{sid}/explain-request?target_tool=run_command&tool_args=%7B%22CommandLine%22%3A%22pip%20install%22%7D")
    assert response.status_code == 200
    data = response.json()
    assert data["target_tool"] == "run_command"
    assert "run_command" in data["explanation"]
    assert data["risk_level"] in ("low", "medium", "high")
