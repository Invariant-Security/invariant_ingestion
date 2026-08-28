"""Thin FastAPI wrapper over invariant_ingestion's own pure modules
(collector/extractor/normalizer/source) -- exposes the same 3-stage
pipeline the monolith's `invariant fetch`/`extract`/`import_document` CLI
commands already ran, minus their Postgres writes (cli/extract.py's
`db.upsert_*` calls, cli/import_document.py's -- persistence is
invariant_api's job now, the only invariant_* service that touches
Postgres).

The fetch->extract handoff stays filesystem-based, exactly as it already
was in the monolith (collector.save_raw_artifact() writes a `.json`
sidecar next to the PDF; extract looks it up by source+document) -- this
service and invariant_api share a `data/raw/` volume, same as fetch/
extract already shared it as two separate CLI invocations.
"""

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from invariant_ingestion import collector, extractor, normalizer, source

app = FastAPI(title="Invariant Ingestion")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


def _known_document(document: str) -> dict:
    known = source.KNOWN_CIS_DOCUMENTS.get(document)
    if known is None:
        known_keys = ", ".join(source.KNOWN_CIS_DOCUMENTS)
        raise HTTPException(404, f"unknown document: {document!r} (known: {known_keys})")
    return known


class RawArtifactResponse(BaseModel):
    source: str
    document: str
    version: str
    content_hash: str
    retrieved_at: str
    path: str


@app.post("/ingestion/fetch/{document}", response_model=RawArtifactResponse)
def fetch(document: str) -> RawArtifactResponse:
    """Ports cli/fetch.py's `fetch()` for one known document (not the
    "fetch every CIS document" bulk mode -- invariant_api always knows
    which document it wants, no reason to expose that here yet).
    """
    known = _known_document(document)
    cis = source.CIS()
    benchmarks = [b for b in cis.discover_benchmarks() if b.document_slug == known["document_slug"]]
    if not benchmarks:
        raise HTTPException(404, f"document not found in CIS Downloads: {known['document_slug']!r}")

    def _version_key(v: str) -> tuple[int, ...]:
        return tuple(int(part) for part in v.split("."))

    latest = max(benchmarks, key=lambda b: (_version_key(b.benchmark_version), b.published_at))
    content, extension = cis.download_discovered(latest)
    artifact = collector.save_raw_artifact(
        content,
        source="cis",
        document=latest.document_slug,
        version=latest.benchmark_version,
        extension=extension,
    )
    return RawArtifactResponse(**artifact.__dict__)


def _latest_raw_artifact_metadata(*, src: str, document: str) -> dict:
    """Same lookup cli/extract.py's own private helper did -- glob broadly,
    filter on each sidecar's own recorded source/document fields (a
    filename-prefix glob isn't safe: "debian_linux_11" is a strict prefix
    of "debian_linux_11_stig"'s filename).
    """
    pattern = f"{src}_*.json"
    candidates = [json.loads(p.read_text()) for p in sorted(collector.DEFAULT_RAW_DIR.rglob(pattern))]
    matches = [m for m in candidates if m["source"] == src and m["document"] == document]
    if not matches:
        raise HTTPException(
            404,
            f"no raw artifact metadata found for {src}/{document} in {collector.DEFAULT_RAW_DIR} "
            "-- call /ingestion/fetch for it first",
        )
    return max(matches, key=lambda m: m["retrieved_at"])


class ExtractedRecommendationResponse(BaseModel):
    external_id: str
    title: str
    scored: bool
    profile_applicability: list[str]
    description: str
    rationale: str
    audit: str
    remediation: str


class ExtractResponse(BaseModel):
    metadata: RawArtifactResponse
    recommendations: list[ExtractedRecommendationResponse]


@app.post("/ingestion/extract/{document}", response_model=ExtractResponse)
def extract(document: str) -> ExtractResponse:
    """Ports cli/extract.py's `extract()`, minus every `db.upsert_*` call
    -- returns the raw artifact's own metadata (so invariant_api can
    upsert source/document/document_version) plus every parsed
    recommendation (so invariant_api can upsert extracted_items).
    """
    known = _known_document(document)
    metadata = _latest_raw_artifact_metadata(src="cis", document=known["document_slug"])
    recommendations = extractor.extract_all_recommendations(Path(metadata["path"]))
    return ExtractResponse(
        metadata=RawArtifactResponse(**metadata),
        recommendations=[ExtractedRecommendationResponse(**r.__dict__) for r in recommendations],
    )


class NormalizeRequest(BaseModel):
    external_id: str
    title: str
    description: str
    scored: bool
    profile_applicability: list[str]
    rationale: str
    audit: str
    remediation: str


class ControlResponse(BaseModel):
    external_id: str
    title: str
    description: str
    scored: bool
    applicability: list[dict]
    applicability_tags: list[str]
    rationale: str
    audit: str
    remediation: str


@app.post("/ingestion/normalize", response_model=list[ControlResponse])
def normalize(items: list[NormalizeRequest]) -> list[ControlResponse]:
    """Ports cli/import_document.py's per-item normalizer.normalize() call,
    minus `db.select_extracted_items`/`db.upsert_control` -- invariant_api
    already has the extracted_items rows (from a prior /ingestion/extract
    call it persisted itself) and passes them back here as plain kwargs,
    same shape normalize() always took.
    """
    controls = [
        normalizer.normalize(
            external_id=item.external_id,
            title=item.title,
            description=item.description,
            scored=item.scored,
            profile_applicability=item.profile_applicability,
            rationale=item.rationale,
            audit=item.audit,
            remediation=item.remediation,
        )
        for item in items
    ]
    return [
        ControlResponse(
            external_id=c.external_id,
            title=c.title,
            description=c.description,
            scored=c.scored,
            applicability=[a.__dict__ for a in c.applicability],
            applicability_tags=c.applicability_tags,
            rationale=c.rationale,
            audit=c.audit,
            remediation=c.remediation,
        )
        for c in controls
    ]
