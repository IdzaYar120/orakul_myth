from pydantic import BaseModel, Field


class Citation(BaseModel):
    num: int
    work: str
    author: str
    ref: str
    text_en: str
    source_url: str | None = None


class Answer(BaseModel):
    text: str
    citations: list[Citation] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)  # entity_ids mentioned in the answer
    grounded: bool = True
