"""Request and response models of the HTTP API that are not service models already."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from delphi.config import settings

Lang = Literal["uk", "en"]
LANGS: tuple[Lang, ...] = ("uk", "en")
Style = Literal["pythia", "scholar"]

UNAVAILABLE_MESSAGES: dict[str, str] = {
    "uk": "Піфія зараз мовчить: оракул недоступний. Енциклопедія і карта працюють.",
    "en": "The Pythia is silent right now: the oracle is unavailable. "
    "The encyclopedia and the map still work.",
}
RATE_LIMIT_MESSAGES: dict[str, str] = {
    "uk": "Забагато запитань за годину. Піфія відпочиває, спробуйте пізніше.",
    "en": "Too many questions this hour. The Pythia is resting, try again later.",
}


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=4000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)
    style: Style = "pythia"
    lang: Lang = "uk"

    @field_validator("question")
    @classmethod
    def _limit_length(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("empty question")
        if len(value) > settings.max_question_chars:
            raise ValueError(f"question longer than {settings.max_question_chars} characters")
        return value

    def history_dicts(self) -> list[dict[str, str]]:
        return [{"role": t.role, "text": t.text} for t in self.history]


class OracleStatus(BaseModel):
    mode: Literal["local", "remote", "off"]
    available: bool
    model: str | None = None
    detail: str | None = None


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    entities: int
    places: int
    passages: int
    oracle: OracleStatus


class StyleOption(BaseModel):
    id: Style
    label: str


class Meta(BaseModel):
    lang: Lang
    langs: list[Lang] = Field(default_factory=lambda: list(LANGS))
    labels: dict[str, dict[str, str]]
    styles: list[StyleOption]
    oracle_mode: Literal["local", "remote", "off"]
    max_question_chars: int


class NearestPlace(BaseModel):
    entity_id: str | None


class ErrorDetail(BaseModel):
    code: str
    message: str
