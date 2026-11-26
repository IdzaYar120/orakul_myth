"""FastAPI application: encyclopedia, map and oracle under /api."""

import hmac
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlmodel import Session, select

from delphi.api.oracle_backends import (
    TOKEN_HEADER,
    LocalOracle,
    OracleBackend,
    OracleUnavailableError,
    backend_from_settings,
)
from delphi.api.ratelimit import RateLimiter
from delphi.api.schemas import (
    RATE_LIMIT_MESSAGES,
    UNAVAILABLE_MESSAGES,
    AskRequest,
    Health,
    Lang,
    Meta,
    NearestPlace,
    StyleOption,
)
from delphi.config import settings
from delphi.db.models import Entity, Passage, Place
from delphi.db.repo import engine
from delphi.encyclopedia.models import (
    EntityCard,
    EntityRef,
    MapFilterOptions,
    MapLayer,
    MythSummary,
)
from delphi.encyclopedia.service import EncyclopediaService, MapService
from delphi.encyclopedia.vocab import vocab_labels
from delphi.rag.models import Answer

STYLE_LABELS = {
    "uk": {"pythia": "Піфія", "scholar": "Науковий"},
    "en": {"pythia": "Pythia", "scholar": "Scholarly"},
}


def _version() -> str:
    try:
        return version("delphi-oracle")
    except PackageNotFoundError:  # pragma: no cover
        return "dev"


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def create_app(oracle: OracleBackend | None = None, limiter: RateLimiter | None = None) -> FastAPI:
    backend = oracle or backend_from_settings()
    rate_limiter = limiter or RateLimiter(settings.oracle_rate_limit)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if isinstance(backend, LocalOracle) and settings.oracle_warmup:
            threading.Thread(target=backend.warmup, daemon=True).start()
        yield

    app = FastAPI(
        title="Delphi Oracle API",
        version=_version(),
        description="Greek mythology: an encyclopedia, a map and a RAG oracle citing the sources.",
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    origins = [o.strip() for o in settings.api_cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", TOKEN_HEADER],
    )
    app.state.oracle = backend
    api = APIRouter(prefix="/api")

    # ------------------------------------------------------------------ service
    @api.get("/health", response_model=Health, tags=["service"])
    async def health() -> Health:
        with Session(engine) as session:
            entities = session.exec(select(func.count()).select_from(Entity)).one()
            places = session.exec(select(func.count()).select_from(Place)).one()
            passages = session.exec(select(func.count()).select_from(Passage)).one()
        return Health(
            version=_version(),
            entities=entities,
            places=places,
            passages=passages,
            oracle=await backend.status(),
        )

    @api.get("/meta", response_model=Meta, tags=["service"])
    def meta(lang: Lang = "uk") -> Meta:
        return Meta(
            lang=lang,
            labels=vocab_labels(lang),
            styles=[StyleOption(id=s, label=label) for s, label in STYLE_LABELS[lang].items()],  # type: ignore[arg-type]
            oracle_mode=backend.mode,  # type: ignore[arg-type]
            max_question_chars=settings.max_question_chars,
        )

    # ------------------------------------------------------------------ encyclopedia
    @api.get("/entities", response_model=list[EntityRef], tags=["encyclopedia"])
    def entities(
        q: str | None = Query(None, max_length=100, description="Search text (uk/en, fuzzy)"),
        type: str | None = Query(None, description="god, titan, hero, mortal, creature, ..."),
        cycle: str | None = Query(None, description="Myth cycle: trojan, argonauts, ..."),
        limit: int = Query(50, ge=1, le=500),
    ) -> list[EntityRef]:
        service = EncyclopediaService()
        if q and q.strip():
            return service.search(q, entity_type=type, cycle=cycle, limit=limit)
        return service.list_entities(entity_type=type, cycle=cycle)[:limit]

    @api.get("/entities/{entity_id}", response_model=EntityCard, tags=["encyclopedia"])
    def entity_card(entity_id: str) -> EntityCard:
        card = EncyclopediaService().get_entity_card(entity_id)
        if card is None:
            raise HTTPException(404, detail={"code": "not_found", "message": entity_id})
        return card

    @api.get("/myths", response_model=list[MythSummary], tags=["encyclopedia"])
    def myths(cycle: str | None = None) -> list[MythSummary]:
        return EncyclopediaService().list_myths(cycle)

    # ------------------------------------------------------------------ map
    @api.get("/map/layer", response_model=MapLayer, tags=["map"])
    def map_layer(
        kinds: list[str] | None = Query(None, description="Place kinds: sanctuary, city, ..."),
        god: str | None = Query(None, description="Only places where this god was worshipped"),
        myth: str | None = Query(None, description="Only places of this myth"),
        routes: list[str] | None = Query(None, description="Hero routes to draw"),
    ) -> MapLayer:
        return MapService().get_map_layer(
            place_kinds=kinds, god_id=god, myth_id=myth, route_ids=routes
        )

    @api.get("/map/filters", response_model=MapFilterOptions, tags=["map"])
    def map_filters() -> MapFilterOptions:
        return MapService().filter_options()

    @api.get("/map/nearest", response_model=NearestPlace, tags=["map"])
    def map_nearest(
        lat: float = Query(..., ge=-90, le=90),
        lon: float = Query(..., ge=-180, le=180),
        max_km: float = Query(30.0, gt=0, le=500),
    ) -> NearestPlace:
        return NearestPlace(entity_id=MapService().nearest_place(lat, lon, max_km))

    # ------------------------------------------------------------------ oracle
    def oracle_guard(request: Request) -> None:
        """Token check for an exposed oracle backend + per-client rate limit."""
        token = request.headers.get(TOKEN_HEADER, "")
        trusted = bool(settings.oracle_token) and hmac.compare_digest(
            token, settings.oracle_token or ""
        )
        if settings.oracle_token and backend.mode == "local" and not trusted:
            raise HTTPException(401, detail={"code": "unauthorized", "message": "bad oracle token"})
        # requests from our own public API (with the token) are counted there, per real client
        if not trusted and not rate_limiter.allow(_client_key(request)):
            lang = "en" if "en" in request.headers.get("accept-language", "")[:2] else "uk"
            raise HTTPException(
                429, detail={"code": "rate_limited", "message": RATE_LIMIT_MESSAGES[lang]}
            )

    @api.post(
        "/oracle/ask",
        response_model=Answer,
        tags=["oracle"],
        dependencies=[Depends(oracle_guard)],
        responses={503: {"description": "The oracle is unavailable (Ollama / host down)"}},
    )
    async def oracle_ask(req: AskRequest) -> Answer:
        try:
            return await backend.ask(req)
        except OracleUnavailableError as exc:
            raise HTTPException(
                503,
                detail={"code": "oracle_unavailable", "message": UNAVAILABLE_MESSAGES[req.lang]},
            ) from exc

    @api.post(
        "/oracle/stream",
        tags=["oracle"],
        dependencies=[Depends(oracle_guard)],
        response_class=StreamingResponse,
        responses={
            200: {
                "content": {"text/event-stream": {}},
                "description": "SSE events: meta, token, done | error",
            }
        },
    )
    async def oracle_stream(req: AskRequest) -> StreamingResponse:
        return StreamingResponse(
            backend.stream(req),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    app.include_router(api)
    return app
