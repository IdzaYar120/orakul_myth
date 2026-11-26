from pydantic import BaseModel, Field


class Citation(BaseModel):
    num: int
    work: str
    author: str
    ref: str
    text_en: str
    translator: str | None = None
    source_url: str | None = None
    notes: list[str] = Field(default_factory=list)
    cited: bool = False  # the answer actually refers to [num]
    entity_ids: list[str] = Field(default_factory=list)  # entities tagged in the passage


class Answer(BaseModel):
    text: str
    citations: list[Citation] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)  # entity ids mentioned in the answer
    grounded: bool = True
    question: str | None = None
    standalone_question: str | None = None  # after condensing a follow-up question
    invalid_citations: list[int] = Field(default_factory=list)  # [n] with no such source
    error: str | None = None  # e.g. LLM not configured; sources are still returned
    lang: str = "uk"
    refused: bool = False  # "the smoke over the tripod gives no answer"
