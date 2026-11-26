# 🔮 Delphi Oracle

> A Python web app over a shared knowledge base of ancient Greek mythology: an AI chat that answers in the voice of the Pythia with quotes from primary sources, and an encyclopedia of gods, heroes and places with an interactive Mediterranean map.

---

## 🏛️ Key features

1. **"Oracle" chat**:
   - Answers in Ukrainian, based on an ancient text corpus (English sources).
   - Two style modes: "Pythia" (solemn, figurative) and "Scientific" (dry, academic).
   - Precise references to primary sources (for example `Hes. Theog. 918`, `Apollod. 1.4.1`) and the English passages in spoilers.
   - Refuses questions the sources do not answer ("Дим над триножником не дає відповіді" — "The smoke over the tripod gives no answer").
2. **Ancient encyclopedia**:
   - Works without an LLM (fast and free, via SQLite + FTS5 + rapidfuzz).
   - Entity cards: descriptions, attributes, spheres of influence, Wikidata ID.
   - Interactive family tree (parents, children, spouses) built with Pyvis/NetworkX.
   - Cross-links: "Ask the oracle about this".
3. **Mediterranean map**:
   - Folium with the CartoDB Positron base layer, coordinates from Pleiades.
   - Place markers (sanctuaries, cities, mountains, islands) with filters.
   - Hero routes (the Odyssey, the Argonauts' voyage).

---

## 🚀 Quick start (local)

### Prerequisites
- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com) — only for the "Oracle" tab (local LLM, no API keys)

### Install and run

1. **Install dependencies** (core + dev tools):
   ```bash
   uv sync --extra dev
   ```
   ML dependencies for RAG (Chroma, sentence-transformers) are needed from stage 3 on: `uv sync --extra dev --extra ml`.

2. **Set up the environment**:
   ```bash
   cp .env.example .env
   ```
   The LLM is needed only for the "Oracle" tab; the encyclopedia and the map work without it.

3. **Initialize the database and seed data** (idempotent; rerunning updates changed records):
   ```bash
   uv run delphi seed
   ```

4. **Start the web interface**:
   ```bash
   uv run streamlit run app/main.py
   ```

---

## 🛠️ CLI commands (`delphi`)

- `uv run delphi seed` — sync SQLite (`delphi.db`) with `data/seed/*.yaml` and rebuild the FTS5 index.
- `uv run delphi wikidata candidates|pull|draft` — import entities from Wikidata and coordinates from Pleiades.
- `uv run delphi ingest [--source ID]` — offline ingest of texts (Chroma + BM25), idempotent.
- `uv run delphi check-refs` — check the source references in the family trees against the corpus.
- `uv run delphi ask "Хто виховував Ахілла?" --style піфія` — ask the oracle from the terminal.
- `uv run delphi eval [--llm] [--judge]` — evaluate on the golden set (`data/eval/golden.yaml`).

---

## 📚 Encyclopedia data

The seed files `data/seed/*.yaml` are the source of truth (edited by hand, tracked in git):
183 entities (gods, titans, heroes, mortals, creatures, artifacts), 88 places, 352 relations, 33 myths.

- **Wikidata** (CC0) — selected entities, Ukrainian/English names, aliases, family relations.
- **Pleiades** (CC BY) — coordinates of ancient places.
- **Manual** — Ukrainian descriptions, spheres, symbols, Roman names, myths, links to places.

Every relation has a `source_ref`: a reference to an ancient text (`Hes. Theog. 453`, `Hom. Il. 5.370`,
`Apollod. 3.13.6`) or `Wikidata` / `manual`. Relations without a primary-source reference are marked ⚠ on the card as not yet verified against the source. Versions of a myth are stored separately (Aphrodite's parents according to Hesiod and according to Homer).
These references were written from memory; after the corpus is ingested (stage 3) they must be checked against the texts.

Pulling from Wikidata:
```bash
uv run delphi wikidata candidates          # ranked candidates (SPARQL, by number of Wikipedia articles)
# add the needed ids/QIDs to data/wikidata/selection.yaml
uv run delphi wikidata pull                # names, aliases, families, coordinates -> data/wikidata/snapshot.yaml
uv run delphi wikidata draft               # add only new records to data/seed/*.yaml
#   (relations in data/wikidata/rejected.yaml, rejected during cleanup, are not suggested)
uv run delphi seed                         # sync SQLite with the YAML (adds, updates, deletes)
```

---

## 🔮 Oracle (RAG)

The corpus: 8 works, ~3,400 passages, all in public-domain translations (see `data/sources.yaml`).

| Work | Translation | Reference format |
|---|---|---|
| Apollodorus, *Library* | Frazer 1921 | `Apollod. 2.4.2` |
| Hesiod, *Theogony*, *Works and Days* | Evelyn-White 1914 | `Hes. Theog. 280`, `Hes. WD 110` |
| Homer, *Iliad*, *Odyssey* | Murray 1924 / 1919 | `Hom. Il. 18.475–18.500` (book.line) |
| *Homeric Hymns* (all 33) | Evelyn-White 1914 | `Hom. Hymn 2 Dem. 80` |
| Apollonius of Rhodes, *Argonautica* | Seaton 1912 | `Ap. Rhod. 1§115` (book§paragraph*) |
| Pausanias, *Description of Greece* | Jones 1918 | `Paus. 10.16.3` |

TEI XML comes from the Perseus Digital Library (markup CC BY-SA 4.0); Apollonius is the Project
Gutenberg plain text (*it has no line numbers, hence paragraph references). Homer's Perseus
"cards" are cut at the line milestones, so citations point to the exact lines.

```bash
uv sync --extra dev --extra ml   # PyTorch, Chroma, sentence-transformers (several GB)
uv run delphi ingest             # download -> parse -> chunks -> tags -> Chroma + BM25 (~50 min on CPU)
uv run delphi check-refs         # check the family tree source_refs against the texts
uv run delphi ask "Хто виховував Ахілла?"
```

How the oracle answers: question -> (rephrasing with the chat history) -> entity linking
(`Ахілла`, `у Дельфах` -> achilles, delphi) -> **the local LLM translates the question into
English** (the corpus is English) -> hybrid search: dense bge-m3 on the English and the Ukrainian
query + BM25 on the English one, Reciprocal Rank Fusion, a boost for passages tagged with the
named entities and a mild genre prior (Apollodorus/Hesiod over Pausanias) -> the LLM sees only
the 5 best passages, cites them as `[1]` -> citation check, entity chips.

**Refusing trap questions before generation.** A cheap threshold on the dense similarity does not
work: trap questions score 0.45–0.59, answerable ones 0.46–0.69. The cross-encoder reranker
(bge-reranker-v2-m3) on the *English* query does separate them: at `MIN_RELEVANCE=0.05` it
refuses 5 of 8 traps before the LLM is called and loses 3 of 72 answerable questions (on the
Ukrainian query its scores are useless). It costs ~7.5 s per question on CPU, so it is off by
default (`RERANK_ENABLED=false`) and meant for a GPU server; without it trap questions are
refused by the LLM itself ("Дим над триножником не дає відповіді").

### Quality (stage 4)

`data/eval/golden.yaml` holds 80 questions: 55 factual, 10 multi-hop (two facts combined),
7 where the sources disagree (the answer must give both versions) and 8 traps. Every expected
reference was checked against the texts.

```bash
uv run delphi eval            # retrieval only: Hit@5, Hit@20, MRR, entity recall (minutes)
uv run delphi eval --llm      # + answers: refusals, citation validity, cited the right passage
uv run delphi eval --judge    # + LLM judge: faithfulness, fact coverage (~1 h locally)
uv run delphi eval --type negative --id q001   # subsets; a JSON report goes to eval/
uv run delphi eval --judge --resume --out eval/report-X.json   # continue an interrupted run
```

Results are saved after every question, so a power cut costs one question, not the run.
Every full run appends a row to `data/eval/history.csv` (kept in git, `--note` describes it).

Retrieval on the 72 answerable questions (the full history is in `data/eval/history.csv`):

| | Hit@5 | Hit@20 | MRR@20 |
|---|---|---|---|
| Stage 3 pipeline: Ukrainian query, dense + BM25* | 57% | 74% | 40% |
| + genre prior, entity boost 0.5, expansion cleaned of unknown aliases | 61% | 78% | 50% |
| + English translation of the query, 3-way fusion (current) | **71%** | **82%** | **57%** |

\* measured before 5 equally valid Apollodorus passages were added to the golden set, so this
row is slightly pessimistic; the other two rows use the current golden set.

Other stage 4 fixes: the entity linker no longer links ordinary words to names ("сталося" was
Talos, "Геракл" was Hera — 43 false positives on the golden set, now 0) and understands case
endings ("у Дельфах", "з Олімпу"); `check-refs` confirms 222 family-tree references in the texts,
none points to a wrong place.

### Local LLM (Ollama)

Answers are generated by a local model through [Ollama](https://ollama.com) — no external APIs or keys.
The default is **MamayLM** (Gemma 3 12B, fine-tuned for Ukrainian by INSAIT):

```bash
# 1. install Ollama from https://ollama.com and start it (tray icon, or `ollama serve`)
# 2. download the model (~7.3 GB, once)
ollama pull hf.co/INSAIT-Institute/MamayLM-Gemma-3-12B-IT-v1.0-GGUF:Q4_K_M
# 3. check it
uv run delphi ask "Хто вбив Медузу?"
```

Comparison on a GTX 1070 (8 GB), same retrieved passages:

| Model | Ukrainian | Answer time |
|---|---|---|
| MamayLM 12B (default) | natural, no invented words | ~25 s (⅓ of the model on CPU) |
| `gemma3:12b` | good, but follows the refusal rules less well | ~60–110 s |
| `qwen2.5:7b` | facts correct, awkward language | ~15 s (fully on GPU) |

Change the model in `.env` (`LLM_MODEL=qwen2.5:7b` for weaker machines). The first answer after
startup is slower: the LLM and bge-m3 are loaded. If Ollama is not running or the model is not pulled,
the oracle says what to do and still shows the found passages. Cloud providers
`LLM_PROVIDER=openai|anthropic` (with a key) are supported too, but optional.

---

## 🗺️ Map

- 85 places with Pleiades coordinates; markers and colors by type (sanctuary, city, mountain, island,
  river, region), grouped when zoomed out; popup with name, description, patron gods.
- Sidebar filters: place type, god (cult places), myth, routes.
- Routes of the **Odyssey** (14 stops) and the **Argonauts** (10 stops) with numbered stops and
  links to the text; dotted lines are traditional identifications, not facts.
- Click a marker → place card on the right; "Show on map" button on a place card.
- 6 mythical places without a location (Hades, Elysium, Ogygia…) are listed under "Off the map".

Shareable links: `?entity=delphi` (card), `?tab=map` (map), `?entity=delphi&tab=map` (map with the place highlighted).

---

## 🗂️ Structure

```
app/                 # Streamlit UI (no business logic)
  main.py            # entry point: streamlit run app/main.py
  views/             # tabs: oracle.py, encyclopedia.py, map.py
  components/        # entity_card.py, family_tree.py, citations.py
src/delphi/          # services (plain Python, does not import Streamlit)
  config.py  cli.py  db/  ingest/  rag/  encyclopedia/  eval/
data/                # seed YAML, sources.yaml, golden set (in git)
tests/
```

> UI tabs live in `app/views/`, not in `app/pages/`: a `pages/` folder next to `main.py`
> turns on Streamlit's automatic multipage navigation.

---

## 🧪 Testing and code checks

```bash
uv run pytest                 # tests (they do not touch your delphi.db — they use a temporary DB)
uv run ruff check .           # linter
uv run ruff format --check .  # formatting
uv run mypy src/              # types
```

Pre-commit (the same checks before every commit):
```bash
uv run pre-commit install
```

CI (GitHub Actions) runs ruff, mypy and pytest and builds the Docker image. The tests do not need
Ollama: the LLM is replaced by a fake model and the embeddings by a hashing stub.

---

## 🐳 Running in Docker

```bash
docker compose run --rm ingest     # one-time: seed SQLite (+ ingest the stage 3 texts)
docker compose up app              # http://localhost:8501
```

The oracle talks to Ollama. Two options:

- **Ollama in a container** (needs the NVIDIA Container Toolkit for GPU):
  ```bash
  docker compose --profile ollama run --rm ollama-pull   # download the model once
  docker compose --profile ollama up
  ```
- **Ollama on the host** (installed on Windows/macOS): in `.env` set
  `OLLAMA_BASE_URL=http://host.docker.internal:11434` and run only `docker compose up app`.

SQLite is stored in the `delphi_storage` volume, the index in `./index`. Settings are read from `.env` (it is not baked into the image).

---

## 📊 Status

| Stage | Status |
|---|---|
| 0. Skeleton | ✅ |
| 1. Data and encyclopedia | ✅ |
| 2. Map | ✅ |
| 3. RAG oracle | ✅ |
| 4. Quality | ✅ |
| 5. Relations and release | ⏳ |

---

## 📜 Data licenses

The texts are early-20th-century translations in the public domain (see `data/sources.yaml`).
Wikidata — CC0; coordinates — [Pleiades](https://pleiades.stoa.org/) (CC BY);
map base layer — Esri World Light Gray / © OpenStreetMap contributors
(CARTO Positron now requires an API key).
