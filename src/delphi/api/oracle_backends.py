"""Where oracle questions are answered: in this process, on another host, or nowhere.

* LocalOracle  — OracleService here (Ollama + the search index): the user's PC or a GPU server.
* RemoteOracle — forwards to another Delphi API in local mode (ORACLE_BACKEND_URL), e.g. the
  user's PC behind a Cloudflare Tunnel; the public host needs no ML stack.
* OffOracle    — encyclopedia and map only.

Streaming uses Server-Sent Events: `meta` (sources found, before generation), `token` (pieces of
the answer), `done` (the final Answer with checked citations) or `error`.
"""

import json
import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any, Protocol

import httpx

from delphi.api.schemas import AskRequest, OracleStatus
from delphi.config import settings
from delphi.rag.models import Answer

log = logging.getLogger(__name__)
TOKEN_HEADER = "X-Oracle-Token"


class OracleUnavailableError(RuntimeError):
    """The oracle cannot answer now (Ollama down, the PC is off, oracle disabled)."""


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class OracleBackend(Protocol):
    mode: str

    async def status(self) -> OracleStatus: ...

    async def ask(self, req: AskRequest) -> Answer: ...

    def stream(self, req: AskRequest) -> AsyncIterator[str] | Iterator[str]: ...


# ---------------------------------------------------------------------- local
class LocalOracle:
    mode = "local"

    def __init__(self, service: Any = None):
        self._service = service

    @property
    def service(self) -> Any:
        if self._service is None:
            from delphi.rag.oracle import OracleService  # heavy: only where it answers

            self._service = OracleService()
        return self._service

    def warmup(self) -> None:
        """Load the embedding model now, so the first question does not wait ~30 s."""
        try:
            from delphi.rag.embeddings import get_embedder

            get_embedder().embed_query("warm up")
        except Exception:  # pragma: no cover - warm-up is best effort
            log.exception("oracle warm-up failed")

    async def status(self) -> OracleStatus:
        if not self.service.retriever.available:
            return OracleStatus(
                mode="local", available=False, detail="search index missing: run delphi ingest"
            )
        if settings.llm_provider == "ollama":
            try:
                async with httpx.AsyncClient(timeout=1.5) as client:
                    (await client.get(f"{settings.ollama_base_url}/api/version")).raise_for_status()
            except httpx.HTTPError:
                return OracleStatus(
                    mode="local",
                    available=False,
                    model=settings.llm_model,
                    detail="Ollama is not running",
                )
        return OracleStatus(mode="local", available=True, model=settings.llm_model)

    def _prepare(self, req: AskRequest) -> Any:
        return self.service.prepare(
            req.question, req.history_dicts(), style=req.style, lang=req.lang
        )

    async def ask(self, req: AskRequest) -> Answer:
        from starlette.concurrency import run_in_threadpool

        answer: Answer = await run_in_threadpool(
            self.service.ask, req.question, req.history_dicts(), req.style, req.lang
        )
        return answer

    def stream(self, req: AskRequest) -> Iterator[str]:
        """Sync generator: Starlette runs it in a thread, so the event loop stays free."""
        from delphi.rag.llm import LLMConfigError

        try:
            prepared = self._prepare(req)
            yield sse(
                "meta",
                {
                    "standalone_question": prepared.standalone,
                    "query_en": prepared.query_en,
                    "grounded": prepared.grounded,
                    "entities": prepared.entity_ids,
                    "citations": [c.model_dump() for c in prepared.citations],
                },
            )
            parts: list[str] = []
            try:
                for piece in self.service.stream(prepared):
                    parts.append(piece)
                    yield sse("token", {"text": piece})
                answer = self.service.finalize(prepared, "".join(parts))
            except LLMConfigError as exc:  # also LLMUnavailableError: sources are still useful
                answer = self.service.finalize(prepared, "", error=str(exc))
            yield sse("done", answer.model_dump())
        except Exception:
            log.exception("oracle stream failed")
            yield sse("error", {"code": "internal_error", "message": "internal error"})


# ---------------------------------------------------------------------- remote
class RemoteOracle:
    mode = "remote"

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._transport = transport

    def _client(self, timeout: float) -> httpx.AsyncClient:
        headers = {TOKEN_HEADER: self.token} if self.token else {}
        return httpx.AsyncClient(
            base_url=self.base_url, headers=headers, timeout=timeout, transport=self._transport
        )

    async def status(self) -> OracleStatus:
        try:
            async with self._client(3.0) as client:
                resp = await client.get("/api/health")
                resp.raise_for_status()
                remote = resp.json().get("oracle", {})
        except (httpx.HTTPError, ValueError):
            return OracleStatus(mode="remote", available=False, detail="oracle host unreachable")
        return OracleStatus(
            mode="remote",
            available=bool(remote.get("available")),
            model=remote.get("model"),
            detail=remote.get("detail"),
        )

    async def ask(self, req: AskRequest) -> Answer:
        try:
            async with self._client(300.0) as client:
                resp = await client.post("/api/oracle/ask", json=req.model_dump())
        except httpx.HTTPError as exc:
            raise OracleUnavailableError(str(exc)) from exc
        if resp.status_code != 200:
            raise OracleUnavailableError(f"oracle host answered {resp.status_code}")
        return Answer.model_validate(resp.json())

    async def stream(self, req: AskRequest) -> AsyncIterator[str]:
        try:
            async with self._client(300.0) as client:
                async with client.stream(
                    "POST", "/api/oracle/stream", json=req.model_dump()
                ) as resp:
                    if resp.status_code != 200:
                        raise OracleUnavailableError(f"oracle host answered {resp.status_code}")
                    async for chunk in resp.aiter_text():
                        yield chunk
        except (httpx.HTTPError, OracleUnavailableError) as exc:
            log.warning("remote oracle failed: %s", exc)
            yield sse("error", {"code": "oracle_unavailable", "message": str(exc)})


# ---------------------------------------------------------------------- off
class OffOracle:
    mode = "off"

    async def status(self) -> OracleStatus:
        return OracleStatus(mode="off", available=False, detail="oracle disabled")

    async def ask(self, req: AskRequest) -> Answer:
        raise OracleUnavailableError("oracle disabled")

    async def stream(self, req: AskRequest) -> AsyncIterator[str]:
        yield sse("error", {"code": "oracle_unavailable", "message": "oracle disabled"})


def backend_from_settings() -> OracleBackend:
    if settings.oracle_mode == "remote":
        if not settings.oracle_backend_url:
            raise ValueError("ORACLE_MODE=remote needs ORACLE_BACKEND_URL")
        return RemoteOracle(settings.oracle_backend_url, settings.oracle_token)
    if settings.oracle_mode == "off":
        return OffOracle()
    return LocalOracle()
