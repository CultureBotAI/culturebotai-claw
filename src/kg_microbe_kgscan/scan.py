"""Europe-PMC knowledge-gap scanner (config-driven, dependency-light).

Stdlib-only HTTP (urllib) so it runs under the same `python3.13` + PYTHONPATH
invocation as kg_microbe_qc. Ported from DisMech's knowledge_gap_scan.py.

Config keys read here beyond the record plumbing (see __main__ for the rest):

  require_topic_in_sentence   default true. The gap-signal SENTENCE itself must
                              mention a topic term (name or synonym); the query
                              only anchors the PAPER, which is how all ten of
                              TraitMech's scanned gaps came out misfiled (#69).
                              Set false to restore recall-first behaviour --
                              relevant for Mechs whose record names are coined
                              multi-word labels no abstract contains verbatim
                              (#79).
  topic_token_min_matches     default 0. When positive, a sentence may also
                              pass by containing at least this many distinctive
                              content tokens from a coined record name. The
                              same tokens expand the Europe PMC query. This is
                              the precision/recall middle setting for
                              CommunityMech (#79); phrase matching remains the
                              default everywhere else.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from typing import Any

EUROPE_PMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

# Gap-signal vocabulary + scoring, ported from DisMech knowledge_gap_scan.py.
GAP_SIGNAL_GROUPS: dict[str, tuple[str, ...]] = {
    "explicit_gap": (
        "knowledge gap", "knowledge gaps", "research gap", "research gaps",
        "unanswered question", "unanswered questions", "unresolved question",
        "unresolved questions",
    ),
    "unclear_unknown": (
        "poorly understood", "remains unclear", "remain unclear", "remained unclear",
        "largely unknown", "is unknown", "are unknown", "remain unknown",
        "remains unknown", "elusive", "not fully understood", "incompletely understood",
    ),
    "future_work": (
        "future studies", "future research", "future investigations", "further studies",
        "further research", "further investigations", "additional studies", "additional research",
    ),
    "controversy_conflict": (
        "controversial", "controversy", "conflicting evidence", "conflicting results",
        "conflicting findings", "contradictory evidence", "inconsistent evidence",
        "inconsistent results", "inconsistent findings",
    ),
    "limitations_barriers": (
        "limited evidence", "limited data", "limitations", "barriers", "challenges",
        "hindered by", "lack of evidence", "lack of data", "absence of evidence", "absence of data",
    ),
}
SIGNAL_WEIGHTS = {
    "explicit_gap": 5, "unclear_unknown": 3, "controversy_conflict": 3,
    "future_work": 2, "limitations_barriers": 1,
}
_ALL_GAP_TERMS = tuple(t for terms in GAP_SIGNAL_GROUPS.values() for t in terms)

# Review-boilerplate assertions that a gap EXISTS without naming one. A sentence
# whose only content is "gaps remain" cannot be curated even when it mentions
# the topic; TraitMech got two of these filed verbatim under two different
# traits (#69, TraitMech#411).
#
# Anchored at BOTH ends, with only filler permitted around the assertion (#77):
# a sentence is contentless only when it consists of essentially nothing but
# the assertion. An unanchored pattern killed "This review identifies
# challenges and knowledge gaps in biofilm dispersal under flow, specifically
# the role of c-di-GMP", and an end-only anchor killed "Despite decades of
# work on the role of c-di-GMP in biofilm dispersal, major knowledge gaps
# remain" -- both specific, curatable gaps whose content sits outside the
# matched phrase.
_FILLER = (
    r"(?:however|nevertheless|nonetheless|still|overall|finally|to\s+date|"
    r"in\s+(?:conclusion|summary))?[,\s]*"
)
CONTENTLESS_PATTERNS = (
    re.compile(
        rf"^\s*{_FILLER}(?:it|this\s+(?:review|study|paper|work|article))?\s*"
        rf"identif\w*\s+(?:ongoing\s+)?challenges\s+and\s+(?:critical\s+)?knowledge\s+gaps"
        rf"(?:\s+for\s+future\s+research)?\s*[.!?]?\s*$",
        re.I,
    ),
    re.compile(
        rf"^\s*{_FILLER}(?:many|several|numerous|important|critical|major|significant)?\s*"
        rf"(?:knowledge\s+gaps?|research\s+gaps?|unanswered\s+questions?|open\s+questions?)\s+"
        rf"(?:remain|persist|exist)s?\s*[.!?]?\s*$",
        re.I,
    ),
)

_WS_RE = re.compile(r"\s+")
_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")
_TOPIC_TOKEN_RE = re.compile(r"[a-z][a-z0-9]+")
_GENERIC_TOPIC_TOKENS = {
    "community",
    "consortium",
    "culture",
    "microbial",
    "microbiome",
    "microorganism",
    "synthetic",
}


def _norm(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").strip())


def split_sentences(text: str) -> list[str]:
    text = _norm(text)
    if not text:
        return []
    return [s.strip() for s in _SENT_RE.split(text) if s.strip()]


def signal_categories(sentence: str) -> list[str]:
    low = sentence.casefold()
    return [cat for cat, terms in GAP_SIGNAL_GROUPS.items()
            if any(t in low for t in terms)]


def _topic_variants(topic_terms) -> tuple[str, ...]:
    """Casefolded topic terms plus separator spellings.

    Slug underscores are tried as spaces, and hyphen<->space both ways (#78):
    `gut-associated` must match "Gut associated microbial communities" and the
    reverse, because separator variance is the commonest difference between a
    record label and the prose that discusses it.
    """
    out: list[str] = []
    seen: set[str] = set()
    for term in topic_terms or ():
        t = _norm(term).casefold()
        if not t:
            continue
        variants = {t, t.replace("_", " ")}
        variants |= {v.replace("-", " ") for v in variants}
        variants |= {v.replace(" ", "-") for v in variants}
        for v in sorted(variants):
            if v not in seen:
                seen.add(v)
                out.append(v)
    return tuple(out)


def _term_pattern(term: str) -> re.Pattern:
    # NOT plain \b...\b: outside a non-word edge character, \b demands an
    # adjacent word character that prose never supplies, so `Fe3+` or
    # `(-)-anisomycin` could never match any sentence (#75). Lookarounds demand
    # a boundary only where the term's own edge is a word character, which
    # still keeps `aerobic` from matching inside "anaerobic" (#71).
    return re.compile(rf"(?<!\w){re.escape(term)}(?!\w)")


def sentence_mentions_topic(sentence: str, topic_terms) -> bool:
    # Word-boundary, not substring (#71): `aerobic` must not pass the gate
    # inside "anaerobic". A spurious pass would silently reproduce the exact
    # misfiling this gate exists to stop.
    low = _norm(sentence).casefold()
    return any(_term_pattern(t).search(low) for t in _topic_variants(topic_terms))


def distinctive_topic_tokens(topic_terms, min_length: int = 5) -> tuple[str, ...]:
    """Stable content tokens for coined labels that prose will not quote whole."""
    tokens: set[str] = set()
    for term in _topic_variants(topic_terms):
        for token in _TOPIC_TOKEN_RE.findall(term):
            if len(token) >= min_length and token not in _GENERIC_TOPIC_TOKENS:
                tokens.add(token)
    return tuple(sorted(tokens))


def sentence_mentions_distinctive_tokens(
    sentence: str, topic_terms, min_matches: int
) -> bool:
    if min_matches <= 0:
        return False
    low = _norm(sentence).casefold()
    matches = sum(
        bool(_term_pattern(token).search(low))
        for token in distinctive_topic_tokens(topic_terms)
    )
    return matches >= min_matches


def is_contentless(sentence: str) -> bool:
    """A gap assertion that names no gap -- review boilerplate, uncuratable."""
    return any(p.search(sentence) for p in CONTENTLESS_PATTERNS)


def extract_gap_signals(
    text: str,
    max_signals: int = 8,
    topic_terms=(),
    require_topic: bool = True,
    topic_token_min_matches: int = 0,
) -> list[dict[str, Any]]:
    """Gap-shaped sentences, anchored to the topic.

    The query already anchors the PAPER to the topic; this anchors the SENTENCE.
    Without it, a topically adjacent paper's hedged sentence about something
    else entirely gets promoted into a Discussion filed under the wrong record
    -- which is how all ten of TraitMech's scanned gaps came out misfiled
    (#69, TraitMech#411). Precision beats recall here: an unfiled gap costs
    nothing, a misfiled one renders as curated content with citations.
    """
    gate = require_topic and bool(topic_terms)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sentence in split_sentences(text):
        cats = signal_categories(sentence)
        if not cats:
            continue
        if gate:
            phrase_match = sentence_mentions_topic(sentence, topic_terms)
            token_match = sentence_mentions_distinctive_tokens(
                sentence, topic_terms, topic_token_min_matches
            )
            if not phrase_match and not token_match:
                continue
        if is_contentless(sentence):
            continue
        key = _norm(sentence).casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append({"categories": cats, "sentence": sentence})
        if len(out) >= max_signals:
            break
    return out


def signal_score(signals: list[dict[str, Any]]) -> int:
    return sum(SIGNAL_WEIGHTS.get(c, 0) for sig in signals for c in sig.get("categories", []))


def _quoted_or(terms) -> str:
    return " OR ".join(f'"{t}"' for t in terms)


def build_query(topic_terms: list[str], context_terms: list[str]) -> str:
    clauses = [f"({_quoted_or(topic_terms)})", f"({_quoted_or(_ALL_GAP_TERMS)})"]
    if context_terms:
        clauses.append(f"({_quoted_or(context_terms)})")
    clauses.append("HAS_ABSTRACT:Y")
    return " AND ".join(clauses)


def europepmc_search(query: str, page_size: int = 25, timeout: float = 30.0) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({
        "query": query, "format": "json", "resultType": "core",
        "pageSize": str(page_size),
    })
    req = urllib.request.Request(f"{EUROPE_PMC_SEARCH_URL}?{params}",
                                 headers={"User-Agent": "kg-microbe-kgscan"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    return data.get("resultList", {}).get("result", []) or []


def _pub_ref(rec: dict[str, Any]) -> str | None:
    pmid = rec.get("pmid") or (rec.get("id") if rec.get("source") == "MED" else None)
    if pmid:
        return f"PMID:{pmid}"
    doi = rec.get("doi")
    return f"DOI:{doi}" if doi else None


def _record_topic(record: dict[str, Any], name_fields, synonym_field) -> tuple[str, list[str]]:
    """Return (primary_name, [name + synonym phrases])."""
    name = ""
    for f in name_fields:
        v = record.get(f)
        if isinstance(v, str) and v.strip():
            name = v.strip()
            break
    terms = [name] if name else []
    syns = record.get(synonym_field) or []
    for s in syns:
        if isinstance(s, str):
            terms.append(s)
        elif isinstance(s, dict):
            for k in ("synonym_text", "value", "name", "label"):
                if isinstance(s.get(k), str):
                    terms.append(s[k])
                    break
    # Dedup, drop very short/ambiguous terms, cap to avoid an enormous query.
    seen, clean = set(), []
    for t in terms:
        t = _norm(t)
        if len(t) >= 4 and t.casefold() not in seen:
            seen.add(t.casefold())
            clean.append(t)
    return name, clean[:6]


def scan_record(record: dict[str, Any], cfg: dict, page_size: int, max_signals: int,
                timeout: float) -> dict[str, Any] | None:
    name_fields = cfg.get("name_fields", ["name", "label", "preferred_term"])
    name, topic_terms = _record_topic(record, name_fields, cfg.get("synonym_field", "synonyms"))
    if not topic_terms:
        return None
    topic_token_min_matches = int(cfg.get("topic_token_min_matches", 0))
    query_terms = list(topic_terms)
    if topic_token_min_matches > 0:
        query_terms.extend(distinctive_topic_tokens(topic_terms))
    query = build_query(query_terms, cfg.get("topic_context_terms", []) or [])
    try:
        results = europepmc_search(query, page_size=page_size, timeout=timeout)
    except Exception as e:  # network/HTTP — report, skip record
        return {"name": name, "error": str(e), "matches": [], "score": 0}
    require_topic = bool(cfg.get("require_topic_in_sentence", True))
    matches: list[dict[str, Any]] = []
    for r in results:
        # Europe PMC abstractText carries structured-abstract HTML (<h4>…</h4>);
        # strip tags so snippets/sentences are clean prose.
        abstract = re.sub(r"<[^>]+>", " ", r.get("abstractText") or "")
        sigs = extract_gap_signals(
            abstract,
            max_signals=max_signals,
            topic_terms=topic_terms,
            require_topic=require_topic,
            topic_token_min_matches=topic_token_min_matches,
        )
        if not sigs:
            continue
        ref = _pub_ref(r)
        if not ref:
            continue
        matches.append({
            "reference": ref, "title": _norm(r.get("title", "")),
            "score": signal_score(sigs), "signals": sigs,
        })
    matches.sort(key=lambda m: m["score"], reverse=True)
    total = sum(m["score"] for m in matches)
    return {"name": name, "topic_terms": topic_terms, "query": query,
            "matches": matches, "score": total}


def prompt_key(discussion: dict[str, Any]) -> str:
    """Identity of the promoted gap sentence, for cross-record dedup.

    The same sentence filed under two records is a strong signal at least one
    filing is wrong (TraitMech got two such pairs in ten discussions), so runs
    keep the best-scored filing and drop the rest (#76). Keyed on the sentence
    rather than discussion_id, which mixes in record_id and so can never
    collide. The sentence is read from evidence[0].snippet, where
    build_discussion() puts it verbatim -- it always emits at least one
    evidence entry, and parsing the sentence back out of the prompt string
    would break on a record name containing ": " (#73).
    """
    evidence = discussion.get("evidence") or []
    if not isinstance(evidence, list) or not evidence or not isinstance(evidence[0], dict):
        return ""
    sentence = evidence[0].get("snippet", "")
    return _norm(sentence).casefold() if isinstance(sentence, str) else ""


def _discussion_id(record_id: str, top_sentence: str) -> str:
    h = hashlib.sha1(f"{record_id}|{_norm(top_sentence).casefold()}".encode()).hexdigest()[:12]
    return f"kgscan-{h}"


def build_discussion(record_id: str, scan: dict[str, Any], max_evidence: int = 4) -> dict[str, Any] | None:
    matches = scan.get("matches") or []
    if not matches:
        return None
    top = matches[0]
    top_sentence = top["signals"][0]["sentence"]
    cats = sorted({c for m in matches for s in m["signals"] for c in s["categories"]})
    evidence = []
    for m in matches[:max_evidence]:
        sig = m["signals"][0]
        evidence.append({
            "reference": m["reference"],
            "supports": "NO_EVIDENCE",
            "evidence_source": "abstract",
            "snippet": sig["sentence"],
            "explanation": f"Gap-signal sentence ({', '.join(sig['categories'])}) from the cited abstract.",
        })
    return {
        "discussion_id": _discussion_id(record_id, top_sentence),
        "prompt": f"Knowledge gap for {scan['name']}: {top_sentence}",
        "kind": "KNOWLEDGE_GAP",
        "status": "OPEN",
        "rationale": ("Surfaced by the Europe PMC literature gap-signal scan "
                      f"(categories: {', '.join(cats)}). Curator review required: "
                      "set attaches_to, refine the prompt, and weigh the cited evidence."),
        "attaches_to": [],
        "evidence": evidence,
        "posed_by": "kg-microbe-kgscan",
    }
