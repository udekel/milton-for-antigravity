import tempfile
import os
import pytest
from app.memory.session_store import SessionStore
from app.models.schemas import FragmentData, TurnData


@pytest.fixture
def temp_store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    store = SessionStore(db_path=db_path)
    yield store
    if os.path.exists(db_path):
        os.remove(db_path)


def test_create_session(temp_store):
    sid = temp_store.create_session(workspace_paths=["/workspace/path"])
    assert sid.startswith("session-")


def test_add_fragment(temp_store):
    sid = temp_store.create_session()
    frag = FragmentData(type="muttering", content="Checking python version...")
    frag_id = temp_store.add_fragment(sid, frag)

    assert frag_id.startswith("frag-")
    frags = temp_store.get_fragments(sid)
    assert len(frags) == 1
    assert frags[0].content == "Checking python version..."


def test_add_turn_batch(temp_store):
    sid = temp_store.create_session()
    turns = [
        TurnData(
            user_prompt="Run unit tests",
            current_action="run_command",
            final_response="All tests passed.",
            fragments=[FragmentData(type="muttering", content="Running pytest...")]
        ),
        TurnData(
            user_prompt="Summarize results",
            current_action="none",
            final_response="Completed.",
            fragments=[FragmentData(type="muttering", content="Done.")]
        )
    ]

    processed = temp_store.add_turn_batch(sid, turns)
    assert processed == 2

    stored_turns = temp_store.get_turns(sid)
    assert len(stored_turns) == 2
    assert stored_turns[0].user_prompt == "Run unit tests"
    assert stored_turns[1].user_prompt == "Summarize results"
