# Chatbot API Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add stateless chatbot endpoint (`POST /api/chat/{bill_id}`). Fetches bill context from DB, builds legislative-analyst system prompt, returns LLM response. Supports Anthropic + OpenAI as interchangeable backends.

**Architecture:** Two new layers beneath FastAPI router: LLM abstraction (`app/chat/llm.py` — `AnthropicClient` / `OpenAIClient` behind common `LLMClient` interface) and `ChatService` (`app/chat/service.py`) that builds system prompt from bill text and delegates to configured LLM client. Router (`app/api/chat.py`) fetches bill context directly from DB (no internal HTTP call), constructs `ChatService`, returns LLM reply. Conversation history owned by client — each request carries full `messages` list. No server-side session state.

**Tech Stack:** FastAPI, SQLAlchemy 2.x, Pydantic v2, anthropic SDK, openai SDK (both already in deps), pytest + `unittest.mock`.

**Depends on:** `2026-04-26-search-bill-data-api.md` — requires `app/main.py`, `app/api/deps.py`, `app/db/models.py` with Plan 1 schema. Apply Plans 1 + 2 before running tests here.
**Required by:** `2026-04-26-frontend.md` — frontend calls `POST /api/chat/{bill_id}` to drive chatbot UI.

---

## Architecture

```mermaid
flowchart TD
    Client -->|POST /api/chat/bill_id\n{messages: [...]}| Router[app/api/chat.py]
    Router -->|query bill by id| PG[(PostgreSQL\nbills table)]
    Router -->|bill_text + messages| ChatService[app/chat/service.py\nBuilds system prompt]
    ChatService -->|system + messages| LLMClient[app/chat/llm.py\nAnthropicClient / OpenAIClient]
    LLMClient -->|API call| Anthropic[Anthropic Claude\nor OpenAI GPT]
    Anthropic --> LLMClient
    LLMClient --> ChatService
    ChatService --> Router
    Router -->|{bill_id, response}| Client

    subgraph Config
        Env[LLM_PROVIDER\nLLM_MODEL\nANTHROPIC_API_KEY\nOPENAI_API_KEY]
    end
    Env --> LLMClient
```

Stateless — client owns conversation history. Each request: fetch bill text → build system prompt → forward `messages` to LLM → return reply.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `app/config.py` | Modify | Add `LLM_PROVIDER`, `LLM_MODEL`, `LLM_MAX_TOKENS`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` |
| `.env.example` | Modify | Document new LLM settings |
| `app/chat/__init__.py` | Create | Package init (empty) |
| `app/chat/llm.py` | Create | `LLMClient` ABC, `AnthropicClient`, `OpenAIClient`, `get_llm_client()` factory |
| `app/chat/service.py` | Create | `ChatService` — system prompt template + `chat(bill_text, messages)` method |
| `app/api/schemas.py` | Modify | Add `ChatMessage`, `ChatRequest`, `ChatResponse` |
| `app/api/chat.py` | Create | `POST /api/chat/{bill_id}` router |
| `app/main.py` | Modify | Mount chat router |
| `tests/chat/__init__.py` | Create | Package init (empty) |
| `tests/chat/test_llm.py` | Create | Tests for `AnthropicClient` and `OpenAIClient` (SDK mocked) |
| `tests/chat/test_service.py` | Create | Tests for `ChatService` (mock `LLMClient`) |
| `tests/api/test_chat.py` | Create | Tests for chat endpoint (mock `get_llm_client`) |

---

## Task 1: Config + `.env.example`

**Files:**
- Modify: `app/config.py`
- Modify: `.env.example`

No tests — Settings tested implicitly when service imports it.

- [ ] **Step 1: Add LLM settings to `app/config.py`**

Add after `EMBEDDING_DIM`:

```python
LLM_PROVIDER: str = "anthropic"      # "anthropic" or "openai"
LLM_MODEL: str = "claude-opus-4-5"
LLM_MAX_TOKENS: int = 1024
ANTHROPIC_API_KEY: str = ""
OPENAI_API_KEY: str = ""
```

- [ ] **Step 2: Update `.env.example`**

Add section after existing embedding settings:

```
# LLM (chatbot backend)
LLM_PROVIDER=anthropic
LLM_MODEL=claude-opus-4-5
LLM_MAX_TOKENS=1024
ANTHROPIC_API_KEY=your-anthropic-key-here
OPENAI_API_KEY=your-openai-key-here
```

- [ ] **Step 3: Commit**

```bash
git add app/config.py .env.example
git commit -m "feat: add LLM provider settings to config"
```

---

## Task 2: LLM Abstraction

**Files:**
- Create: `app/chat/__init__.py`
- Create: `app/chat/llm.py`
- Create: `tests/chat/__init__.py`
- Create: `tests/chat/test_llm.py`

`LLMClient` ABC defines single `complete(system, messages)` method. `AnthropicClient` passes `system` as top-level param to `messages.create`. `OpenAIClient` prepends `{"role": "system", ...}` to message list. Factory `get_llm_client()` reads `settings.LLM_PROVIDER`. Tests mock SDK constructors directly — no real API calls.

- [ ] **Step 1: Write failing tests**

Create `tests/chat/__init__.py` (empty).

Create `tests/chat/test_llm.py`:

```python
from unittest.mock import patch, MagicMock
from app.chat.llm import AnthropicClient, OpenAIClient, get_llm_client
from app.config import settings


def test_anthropic_client_calls_messages_create():
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text="Bills address taxation.")]
    with patch("app.chat.llm.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_resp
        client = AnthropicClient()
        result = client.complete(
            system="You are a legislative analyst.",
            messages=[{"role": "user", "content": "What is this about?"}],
        )
    assert result == "Bills address taxation."
    MockAnthropic.return_value.messages.create.assert_called_once()


def test_anthropic_client_passes_system_and_messages():
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text="reply")]
    with patch("app.chat.llm.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_resp
        client = AnthropicClient()
        client.complete(
            system="sys prompt",
            messages=[{"role": "user", "content": "q"}],
        )
    call_kwargs = MockAnthropic.return_value.messages.create.call_args[1]
    assert call_kwargs["system"] == "sys prompt"
    assert call_kwargs["messages"] == [{"role": "user", "content": "q"}]


def test_openai_client_calls_chat_completions():
    mock_choice = MagicMock()
    mock_choice.message.content = "OpenAI reply"
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    with patch("app.chat.llm.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create.return_value = mock_resp
        client = OpenAIClient()
        result = client.complete(
            system="sys",
            messages=[{"role": "user", "content": "q"}],
        )
    assert result == "OpenAI reply"


def test_openai_client_prepends_system_message():
    mock_choice = MagicMock()
    mock_choice.message.content = "reply"
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    with patch("app.chat.llm.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create.return_value = mock_resp
        client = OpenAIClient()
        client.complete(system="sys", messages=[{"role": "user", "content": "q"}])
    call_kwargs = MockOpenAI.return_value.chat.completions.create.call_args[1]
    msgs = call_kwargs["messages"]
    assert msgs[0] == {"role": "system", "content": "sys"}
    assert msgs[1] == {"role": "user", "content": "q"}


def test_get_llm_client_returns_anthropic_by_default():
    with patch.object(settings, "LLM_PROVIDER", "anthropic"):
        client = get_llm_client()
    assert isinstance(client, AnthropicClient)


def test_get_llm_client_returns_openai():
    with patch.object(settings, "LLM_PROVIDER", "openai"):
        client = get_llm_client()
    assert isinstance(client, OpenAIClient)
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/chat/test_llm.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.chat'`

- [ ] **Step 3: Create `app/chat/__init__.py`** (empty)

- [ ] **Step 4: Implement `app/chat/llm.py`**

```python
from abc import ABC, abstractmethod
from anthropic import Anthropic
from openai import OpenAI
from app.config import settings


class LLMClient(ABC):
    @abstractmethod
    def complete(self, system: str, messages: list[dict]) -> str: ...


class AnthropicClient(LLMClient):
    def complete(self, system: str, messages: list[dict]) -> str:
        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=settings.LLM_MODEL,
            max_tokens=settings.LLM_MAX_TOKENS,
            system=system,
            messages=messages,
        )
        return resp.content[0].text  # type: ignore[union-attr]


class OpenAIClient(LLMClient):
    def complete(self, system: str, messages: list[dict]) -> str:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        all_messages = [{"role": "system", "content": system}] + messages
        resp = client.chat.completions.create(
            model=settings.LLM_MODEL,
            max_tokens=settings.LLM_MAX_TOKENS,
            messages=all_messages,
        )
        return resp.choices[0].message.content or ""


def get_llm_client() -> LLMClient:
    if settings.LLM_PROVIDER == "anthropic":
        return AnthropicClient()
    return OpenAIClient()
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/chat/test_llm.py -v
```

Expected: 6 PASSED.

- [ ] **Step 6: Commit**

```bash
git add app/chat/__init__.py app/chat/llm.py tests/chat/__init__.py tests/chat/test_llm.py
git commit -m "feat: LLM client abstraction (Anthropic + OpenAI)"
```

---

## Task 3: Chat Service

**Files:**
- Create: `app/chat/service.py`
- Create: `tests/chat/test_service.py`

`ChatService` owns system prompt template. Tests use mock `LLMClient` — verify system prompt includes bill text, messages forwarded unchanged, prompt is non-partisan and instructs citation.

- [ ] **Step 1: Write failing tests**

Create `tests/chat/test_service.py`:

```python
from unittest.mock import MagicMock
from app.chat.service import ChatService


def _mock_llm(reply: str = "test reply") -> MagicMock:
    llm = MagicMock()
    llm.complete.return_value = reply
    return llm


def test_chat_returns_llm_reply():
    service = ChatService(llm=_mock_llm("This bill addresses taxes."))
    result = service.chat(
        bill_text="H.R. 1 — Tax Reform Act...",
        messages=[{"role": "user", "content": "What is this bill about?"}],
    )
    assert result == "This bill addresses taxes."


def test_chat_includes_bill_text_in_system_prompt():
    llm = _mock_llm()
    service = ChatService(llm=llm)
    service.chat(
        bill_text="SECTION 1. Climate provisions.",
        messages=[{"role": "user", "content": "Tell me about climate."}],
    )
    system_arg = llm.complete.call_args[1]["system"]
    assert "SECTION 1. Climate provisions." in system_arg


def test_chat_passes_messages_to_llm():
    llm = _mock_llm()
    service = ChatService(llm=llm)
    messages = [
        {"role": "user", "content": "What does section 3 say?"},
        {"role": "assistant", "content": "Section 3 covers..."},
        {"role": "user", "content": "How much funding?"},
    ]
    service.chat(bill_text="bill text", messages=messages)
    messages_arg = llm.complete.call_args[1]["messages"]
    assert messages_arg == messages


def test_chat_system_prompt_is_nonpartisan():
    llm = _mock_llm()
    service = ChatService(llm=llm)
    service.chat(bill_text="anything", messages=[{"role": "user", "content": "q"}])
    system_arg = llm.complete.call_args[1]["system"]
    assert "non-partisan" in system_arg.lower() or "neutral" in system_arg.lower()


def test_chat_system_prompt_instructs_citation():
    llm = _mock_llm()
    service = ChatService(llm=llm)
    service.chat(bill_text="text", messages=[{"role": "user", "content": "q"}])
    system_arg = llm.complete.call_args[1]["system"]
    assert "section" in system_arg.lower() or "cite" in system_arg.lower()
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/chat/test_service.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.chat.service'`

- [ ] **Step 3: Implement `app/chat/service.py`**

```python
from app.chat.llm import LLMClient

_SYSTEM_PROMPT = """\
You are an expert non-partisan Legislative Analyst. \
Answer questions about the bill below based solely on its text. \
Cite the specific section or provision for every claim. \
If the bill does not address a topic, state: \
"The provided text does not cover this topic." \
Use plain English and neutral tone.

BILL TEXT:
{bill_text}\
"""


class ChatService:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def chat(self, bill_text: str, messages: list[dict]) -> str:
        system = _SYSTEM_PROMPT.format(bill_text=bill_text)
        return self.llm.complete(system=system, messages=messages)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/chat/test_service.py -v
```

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add app/chat/service.py tests/chat/test_service.py
git commit -m "feat: ChatService with legislative analyst system prompt"
```

---

## Task 4: Chat Schemas + Router

**Files:**
- Modify: `app/api/schemas.py`
- Create: `app/api/chat.py`
- Modify: `app/main.py`
- Create: `tests/api/test_chat.py`

`ChatMessage` uses `Literal["user", "assistant"]` — invalid roles rejected with 422. `ChatRequest` validator rejects empty `messages` list. Router fetches `Bill` by `bill_id`, builds `bill_text` from `title + summary`, constructs `ChatService` with live LLM client. Tests mock `get_llm_client` at `app.api.chat` — no real API calls, no model load.

- [ ] **Step 1: Write failing tests**

Create `tests/api/test_chat.py`:

```python
from unittest.mock import patch, MagicMock
from tests.api.conftest import make_bill


def _mock_llm_client(reply: str = "LLM reply") -> MagicMock:
    client = MagicMock()
    client.complete.return_value = reply
    return client


def test_chat_returns_200(client, db):
    make_bill(db)
    with patch("app.api.chat.get_llm_client", return_value=_mock_llm_client()):
        resp = client.post(
            "/api/chat/118-hr-1",
            json={"messages": [{"role": "user", "content": "What is this bill?"}]},
        )
    assert resp.status_code == 200


def test_chat_returns_response_body(client, db):
    make_bill(db)
    with patch("app.api.chat.get_llm_client", return_value=_mock_llm_client("Great bill.")):
        data = client.post(
            "/api/chat/118-hr-1",
            json={"messages": [{"role": "user", "content": "Tell me about it."}]},
        ).json()
    assert data["bill_id"] == "118-hr-1"
    assert data["response"] == "Great bill."


def test_chat_bill_not_found(client, db):
    with patch("app.api.chat.get_llm_client", return_value=_mock_llm_client()):
        resp = client.post(
            "/api/chat/999-hr-9999",
            json={"messages": [{"role": "user", "content": "q"}]},
        )
    assert resp.status_code == 404


def test_chat_passes_bill_text_to_service(client, db):
    make_bill(db, title="Climate Reform Act", summary="Reduces carbon emissions.")
    captured = {}
    with patch("app.api.chat.get_llm_client") as mock_factory:
        llm = MagicMock()
        llm.complete.side_effect = lambda system, messages: (
            captured.update({"system": system}) or "ok"
        )
        mock_factory.return_value = llm
        client.post(
            "/api/chat/118-hr-1",
            json={"messages": [{"role": "user", "content": "q"}]},
        )
    assert "Climate Reform Act" in captured["system"]
    assert "Reduces carbon emissions." in captured["system"]


def test_chat_invalid_role_returns_422(client, db):
    make_bill(db)
    resp = client.post(
        "/api/chat/118-hr-1",
        json={"messages": [{"role": "admin", "content": "hack"}]},
    )
    assert resp.status_code == 422


def test_chat_empty_messages_returns_422(client, db):
    make_bill(db)
    resp = client.post("/api/chat/118-hr-1", json={"messages": []})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/api/test_chat.py -v
```

Expected: `ImportError: cannot import name 'chat' from 'app.api'`

- [ ] **Step 3: Add chat schemas to `app/api/schemas.py`**

Add to imports at top of `app/api/schemas.py`:

```python
from typing import Literal
from pydantic import BaseModel, model_validator
```

Append to end of `app/api/schemas.py`:

```python
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]

    @model_validator(mode="after")
    def messages_not_empty(self) -> "ChatRequest":
        if not self.messages:
            raise ValueError("messages must not be empty")
        return self


class ChatResponse(BaseModel):
    bill_id: str
    response: str
```

- [ ] **Step 4: Implement `app/api/chat.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.schemas import ChatRequest, ChatResponse
from app.chat.llm import get_llm_client
from app.chat.service import ChatService
from app.db import models

router = APIRouter()


@router.post("/chat/{bill_id}", response_model=ChatResponse)
def chat(bill_id: str, request: ChatRequest, db: Session = Depends(get_db)):
    bill = db.query(models.Bill).filter(models.Bill.bill_id == bill_id).first()
    if bill is None:
        raise HTTPException(status_code=404, detail=f"Bill {bill_id!r} not found")

    parts = [bill.title or "", bill.summary or ""]
    bill_text = "\n\n".join(p for p in parts if p).strip() or bill_id

    llm = get_llm_client()
    service = ChatService(llm=llm)
    reply = service.chat(
        bill_text=bill_text,
        messages=[m.model_dump() for m in request.messages],
    )
    return ChatResponse(bill_id=bill_id, response=reply)
```

- [ ] **Step 5: Mount chat router in `app/main.py`**

Add import and `include_router`:

```python
from fastapi import FastAPI
from app.api import bills, search, chat

app = FastAPI(title="Bill Retrieval API", version="0.1.0")
app.include_router(bills.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
```

- [ ] **Step 6: Run chat tests**

```bash
uv run pytest tests/api/test_chat.py -v
```

Expected: 6 PASSED.

- [ ] **Step 7: Run full suite**

```bash
uv run pytest -v
```

Expected: all tests PASS (ingestion + model + API bills + API search + chat = all green).

- [ ] **Step 8: Commit**

```bash
git add app/api/schemas.py app/api/chat.py app/main.py tests/api/test_chat.py
git commit -m "feat: POST /api/chat/{bill_id} chatbot endpoint"
```

---

## Task 5: Smoke-Test Chatbot Endpoint

No new tests — verify end-to-end against live LLM.

- [ ] **Step 1: Ensure `.env` has `ANTHROPIC_API_KEY` set**

```bash
grep ANTHROPIC_API_KEY .env
```

Expected: non-empty value.

- [ ] **Step 2: Start server**

```bash
docker compose up -d postgres
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

- [ ] **Step 3: Smoke-test**

```bash
# First get a real bill_id from DB (requires Universe DL from Plan 1)
# Or insert a test bill manually
curl -s -X POST http://localhost:8000/api/chat/118-hr-1234 \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is this bill about?"}]}' \
  | python -m json.tool
```

Expected: `{"bill_id": "118-hr-1234", "response": "...LLM reply..."}`.

- [ ] **Step 4: Test multi-turn conversation**

```bash
curl -s -X POST http://localhost:8000/api/chat/118-hr-1234 \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "What does section 3 cover?"},
      {"role": "assistant", "content": "Section 3 covers funding..."},
      {"role": "user", "content": "How much?"}
    ]
  }' | python -m json.tool
```

---

## Open Questions / Deferred

1. **Prompt caching:** Anthropic supports prompt caching (beta) for large system prompts — up to 90% cost reduction on repeated bill queries. Add `cache_control: {"type": "ephemeral"}` to system block when bill text exceeds ~1000 tokens. One-line change in `AnthropicClient.complete()`. `ChatService` interface stable — no callers affected.
2. **Streaming:** Both SDKs support SSE streaming. Add `stream` param to `LLMClient.complete()`, return `StreamingResponse` from router. Interface designed for easy extension.
3. **Token limits:** Long conversation histories hit context limits. Future: trim oldest messages when `sum(len(m["content"]) for m in messages) > threshold`. Not needed for MVP.
4. **Rate limiting:** Chat endpoint calls external API on every request. Add simple in-memory rate limiter (e.g., `slowapi`) before internet exposure.
5. **Error handling:** Both clients surface SDK exceptions directly. Future: catch `anthropic.APIError` / `openai.OpenAIError`, return `503` with user-friendly message.
6. **OpenAI `content` nullability:** `resp.choices[0].message.content` is `Optional[str]` — returns `None` if model uses tool calls or refusal. `OpenAIClient.complete()` guards with `or ""`. Non-issue for plain chat; revisit if tools added.
7. **Anthropic content block type:** `resp.content[0].text` assumes `TextBlock`. Safe for plain chat (no tools configured). Add explicit `cast` or type check if tool use added later.
