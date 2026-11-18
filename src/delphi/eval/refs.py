"""Check `source_ref` of seed relations against the ingested corpus (`delphi check-refs`).

For a relation such as (zeus, parent_of, apollo, "Hes. Theog. 918") we find the passages that
contain line 918 of the Theogony and check that both entities are tagged there. References were
written from memory during curation, so this is how they get verified.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlmodel import Session, select

from delphi.config import settings
from delphi.db.models import Passage, PassageEntity

# Perseus line numbers may carry a letter for interpolated lines: "929j"
_RANGE = re.compile(
    r"^(?P<prefix>.+?) (?P<start>[\d.]+[a-z]?)(?:–(?P<end>[\d.]+[a-z]?))?(?: \(\d+/\d+\))?$"
)
LINE_BLOCK_SPAN = 5  # a Perseus line block covers ~5 verse lines after its start


@dataclass
class RefCheck:
    src_id: str
    rel: str
    dst_id: str
    source_ref: str
    status: str  # ok | entity_missing | ref_not_found | not_ingested
    detail: str = ""


def _key(ref: str) -> tuple[int, ...]:
    return tuple(int(re.sub(r"[a-z]$", "", p)) for p in ref.split(".") if p[:1].isdigit())


def _parse(ref: str) -> tuple[str, tuple[int, ...], tuple[int, ...]] | None:
    m = _RANGE.match(ref.strip())
    if not m:
        return None
    start = _key(m["start"])
    end = _key(m["end"]) if m["end"] else start
    return m["prefix"], start, end


def _contains(passage_ref: str, target: str) -> bool:
    p, t = _parse(passage_ref), _parse(target)
    if not p or not t or p[0] != t[0]:
        return False
    _, start, end = p
    point = t[1]
    if len(point) == 1 and len(start) == 1:  # line numbers
        return start[0] <= point[0] <= end[0] + LINE_BLOCK_SPAN - 1
    return start <= point <= end


def check_relation_refs(session: Session, relations_path: Path | None = None) -> list[RefCheck]:
    path = relations_path or settings.data_dir / "seed" / "relations.yaml"
    with open(path, encoding="utf-8") as f:
        relations = yaml.safe_load(f) or []

    passages = session.exec(select(Passage)).all()
    prefixes = {(_parse(p.ref) or ("",))[0] for p in passages}
    tags: dict[str, set[str]] = {}
    for pe in session.exec(select(PassageEntity)).all():
        tags.setdefault(pe.passage_id, set()).add(pe.entity_id)

    results = []
    for r in relations:
        ref = r["source_ref"]
        parsed = _parse(ref)
        base = RefCheck(r["src_id"], r["rel"], r["dst_id"], ref, "not_ingested")
        if parsed is None or parsed[0] not in prefixes:
            results.append(base)
            continue
        hits = [p for p in passages if _contains(p.ref, ref)]
        if not hits:
            base.status, base.detail = "ref_not_found", "немає уривка з таким місцем"
            results.append(base)
            continue
        mentioned = set().union(*(tags.get(p.id, set()) for p in hits))
        missing = [e for e in (r["src_id"], r["dst_id"]) if e not in mentioned]
        if missing:
            base.status = "entity_missing"
            base.detail = f"не згадано: {', '.join(missing)} у {', '.join(p.ref for p in hits)}"
        else:
            base.status, base.detail = "ok", ", ".join(p.ref for p in hits)
        results.append(base)
    return results
