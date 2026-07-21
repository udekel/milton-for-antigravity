# Design Document: Milton Agent Backend (Local Implementation)

## 1. Executive Summary

**Milton** is an AI-based system designed to collect, distill, and analyze the intermediate "stream of thought" (mutterings, reasoning steps, tool call parameters, and execution outputs) produced by coding agents such as Antigravity and Jetski.

This design document outlines a **100% local, self-contained implementation** of the Milton Agent API and Session Memory backend before any cloud deployment.

---

## 2. System Architecture

```mermaid
graph TD
    subgraph Client / Harness (Local IDE or CLI)
        A[Jetski / Antigravity Harness] -->|Hook Events| B[Milton Hook Plugin]
    end

    subgraph Milton Local Agent Server (FastAPI + Python ADK)
        B -->|HTTP POST /api/v1/fragment| C[API Route Handler]
        B -->|HTTP POST /api/v1/turn| C
        
        C --> D[Session Memory Store]
        
        D <--> E[(SQLite / File Persistence)]
        
        C -->|Summarize Request| F[Muttering Analyzer Agent]
        C -->|Explain Request| G[Permission Request Explainer Agent]
        
        F -->|Gemini API / Local Model| H[Reasoning Engine]
        G -->|Gemini API / Local Model| H
    end

    subgraph Output / UI Feedback
        F -->|Structured Summary| B
        G -->|Permission Rationale| B
    end
```

---

## 3. Core Component Design

### 3.1 Local FastAPI Server (`app/main.py`)
A lightweight, high-performance local HTTP server hosting the 4 core Milton API endpoints.

- **Port**: `8000` (configurable via environment variables)
- **Framework**: `FastAPI` + `uvicorn`
- **Serialization**: `Pydantic v2` models matching the four spec methods.

### 3.2 The Four API Endpoints & Streaming vs. Batching

#### Relationship between `ProcessTurn` and `ProcessFragment`:
- **`ProcessFragment` (Streaming / Real-Time)**: Pushes individual mutterings, thoughts, or tool events **as they happen in real-time** during an active turn. Used when the client harness uses hooks to stream low-latency events.
- **`ProcessTurn` (Batched Push)**: Pushes a **batch of events or turn data** at turn completion. Making `ProcessTurn` batched allows clients to send an array of mutterings/fragments (or even multiple completed turns) in a single HTTP payload, avoiding network overhead when real-time streaming isn't needed or when catching up after a turn finishes.

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/session/{session_id}/turn` | **ProcessTurn (Batched)**: Accepts a batch of turn events (user prompt, list of mutterings/fragments, tool calls, and final response) or multiple turn objects in a single payload. Appends and indexes all items in session memory. |
| `POST` | `/api/v1/session/{session_id}/fragment` | **ProcessFragment**: Streams a single real-time muttering/fragment into session memory as it occurs during an active turn. |
| `GET` | `/api/v1/session/{session_id}/summary` | **SummarizeMutterings**: Analyzes full session or turn trajectory from session memory and returns a structured summary. |
| `GET` | `/api/v1/session/{session_id}/explain-request` | **ExplainUserRequest**: Translates preceding mutterings in session memory to explain a specific permission request. |

---

## 4. Session Memory Architecture (`app/memory/`)

Session memory is critical because Milton needs to retain multi-turn context (what was attempted 3 turns ago, what files were edited earlier, what errors occurred) to explain *why* the agent is currently requesting permission.

### Memory Data Structure

```python
class SessionState:
    session_id: str
    created_at: datetime
    updated_at: datetime
    turns: List[TurnData]
    active_fragments: List[FragmentData]
    precomputed_summaries: Dict[str, SummaryResult]
```

### Storage Mechanism for Local Build
1. **In-Memory Cache**: `Dict[str, SessionState]` for instant sub-millisecond retrieval during active turns.
2. **SQLite File Database (`milton_sessions.db`)**: Persistent local storage ensuring session memory survives local server restarts.

---

## 5. Agent Reasoning Engine (`app/agents/`)

Milton uses specialized agent prompts built with **Google ADK (Agent Development Kit)**:

1. **`MutteringAnalyzerAgent`**:
   - **Input**: Raw stream-of-thought text + tool call logs.
   - **Task**: Categorize thoughts into:
     - *Actions Executed*
     - *Hypotheses Tested & Rejected*
     - *Key Decisions Made*
     - *Safety / Risk Callouts*
   - **Output**: JSON matching `SummaryResult` schema.

2. **`RequestExplainerAgent`**:
   - **Input**: Preceding mutterings + target tool call (`run_command`, `write_file`).
   - **Task**: Explain *why* the model needs this specific permission in simple, non-technical terms.
   - **Output**: String explanation injected into the UI permission prompt.

---

## 6. Directory Structure

```
milton-for-antigravity/
├── README.md
├── docs/
│   └── DESIGN.md                      # System Design Document
├── requirements.txt                   # FastAPI, uvicorn, pydantic, google-genai, pytest
├── run_local.sh                       # Script to start local Milton server
├── app/
│   ├── __init__.py
│   ├── main.py                        # FastAPI entry point
│   ├── config.py                      # Local app settings & port config
│   ├── models/
│   │   └── schemas.py                 # Pydantic data schemas
│   ├── memory/
│   │   ├── session_store.py           # In-memory + SQLite persistence
│   │   └── schemas.py
│   ├── agents/
│   │   ├── analyzer.py                # ADK Muttering Analyzer Agent
│   │   └── explainer.py               # ADK Request Explainer Agent
│   └── api/
│       └── routes.py                  # API route implementations
├── plugins/
│   └── antigravity/
│       ├── plugin.py                  # HTTP client sending events to local server
│       └── milton_hook.py             # CLI hook calling local server
└── tests/
    ├── test_memory.py                 # Session store tests
    └── test_api.py                    # Local API endpoint integration tests
```

---

## 7. Local Implementation & Testing Plan

1. **Step 1: Pydantic Schemas & Session Store**:
   Build in-memory + SQLite session storage and verify multi-turn persistence.
2. **Step 2: FastAPI Local Server**:
   Implement all 4 endpoints and launch locally on `http://localhost:8000`.
3. **Step 3: ADK Agent Integration**:
   Connect Gemini API / ADK Python SDK for background muttering analysis.
4. **Step 4: Update Plugin to HTTP Mode**:
   Update `milton_hook.py` to forward events directly to `http://localhost:8000/api/v1/...` and render server-generated summaries.
5. **Step 5: End-to-End Local Verification**:
   Execute interactive CLI sessions to verify real-time processing and session memory retrieval.
