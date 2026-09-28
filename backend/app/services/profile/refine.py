"""A research profile made readable and consistent (remediation Phase 6).

Deterministic, and run on every profile when it is built and when it is
read, so profiles extracted before this existed get the same treatment
without a second (paid) extraction. It never adds a claim the paper doesn't
make:

- the abstract loses its label, markup and publisher block (normalize/text.py),
  and a short summary is taken from its own sentences -- the one stating what
  the paper does, and the one stating what it found -- never written anew;
- a text that isn't the abstract (a PDF where none was found) is not called one;
- an evaluation metric gets the value the paper reports only when that value
  is written in the metric's own verified evidence and belongs to it
  unambiguously ("precision and recall of 96% and 93% respectively" gives
  each its own); otherwise it has none, and says so;
- names read the same way everywhere: sentence case, no stray full stop,
  no line-break debris;
- one thing is listed once: near-identical items in a list merge, and an item
  already listed under a more specific heading (a named model, a dataset)
  leaves the vaguer ones (methods, entities).

A user's own edits are left exactly as they wrote them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.domain.profile import (
    ProfileField,
    ProfileList,
    ProvenanceStatus,
    ReportedValue,
    ResearchProfile,
)
from app.services.normalize.text import clean_abstract, clean_text

# --- sentences and the summary ----------------------------------------------

_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\d\"'(\[])")
_ABBREVIATIONS = ("e.g.", "i.e.", "et al.", "etc.", "vs.", "Fig.", "fig.", "Eq.", "No.", "cf.", "approx.")
_CONTRIBUTION = re.compile(
    r"\b(?:this (?:paper|study|work|research|article|thesis|survey|review|chapter)"
    r"|in this (?:paper|study|work|article)|here,? we"
    r"|we (?:propose|present|introduce|develop|design|investigate|study|describe|report|address|explore|evaluate"
    r"|examine|analy[sz]e|build|train|show|demonstrate)"
    r"|(?:is|are) (?:proposed|presented|introduced|developed)"
    r"|proposes|presents|introduces|develops|investigates|examines)\b",
    re.IGNORECASE,
)
# what a paper found: a reported figure first, else the words results come in
_RESULT_FIGURE = re.compile(r"\d(?:[.,]\d+)?\s?%|(?<![\w.])\d+\.\d+(?![\w.])")
_RESULT_WORDS = re.compile(
    r"\b(?:results? (?:show|shows|indicate|demonstrate|reveal|suggest)|achiev(?:e|es|ed|ing)|outperform(?:s|ed|ing)?"
    r"|significantly improv(?:es|ed)|accuracy of|we find|we found)\b",
    re.IGNORECASE,
)
SUMMARY_MAX_WORDS = 70


def sentences(text: str) -> list[str]:
    out: list[str] = []
    for part in _SPLIT.split(text):
        if out and out[-1].endswith(_ABBREVIATIONS):
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return [s.strip() for s in out if s.strip()]


def summarize(abstract: str) -> str:
    """At most two of the abstract's own sentences: what the paper does, and
    what it found. A short abstract is its own summary."""
    sents = sentences(abstract)
    if not sents:
        return ""

    def words(s: str) -> int:
        return len(s.split())

    if len(sents) <= 2 and sum(map(words, sents)) <= SUMMARY_MAX_WORDS:
        return " ".join(sents)
    contribution = next((i for i, s in enumerate(sents) if _CONTRIBUTION.search(s)), 0)
    later = range(contribution + 1, len(sents))
    result = next((i for i in later if _RESULT_FIGURE.search(sents[i])), None)
    if result is None:
        result = next((i for i in later if _RESULT_WORDS.search(sents[i])), None)
    if result is None or words(sents[contribution]) + words(sents[result]) > SUMMARY_MAX_WORDS:
        return sents[contribution]
    return f"{sents[contribution]} {sents[result]}"


# --- reported metric values -------------------------------------------------

# a figure a metric is reported in: a percentage, a decimal, or a number with a unit.
# Bare integers are left out: in a sentence they are counts, years, model sizes.
_VALUE = re.compile(
    # "approximately 95%-97%" is one value: its qualifier and range are part of what the paper says
    r"(?:(?:approximately|about|around|nearly|over|up to|~)\s?)?"
    r"(?<![\w.])(?:[-+]?\d+(?:\.\d+)?\s?%?\s?[-–]\s?\d+(?:\.\d+)?\s?%"
    r"|[-+]?\d+(?:\.\d+)?\s?%"
    r"|[-+]?\d*\.\d+(?:\s?(?:ms|s|fps|dB|x|×)\b)?"
    r"|\d+(?:,\d{3})*\s?(?:ms|fps|dB|x|×)(?!\w))",
    re.IGNORECASE,
)
# values joined only by these belong to a series or a change, not to one result
_CONNECTOR = re.compile(r"^\s*(?:,|,?\s*and|,?\s*or|to|vs\.?|/|→|->)?\s*$", re.IGNORECASE)
_BRACKETED = re.compile(r"([^()]*)\(([A-Za-z][A-Za-z0-9@\-]{0,9})\)")


def _acronyms(value: str) -> list[str]:
    """Bracketed abbreviations of the words before them -- "Principal
    Component Analysis (PCA)", "Long Short-Term Memory (LSTM)" -- never a
    qualifier like "Precision (VGG16)"."""
    out: list[str] = []
    for before, bracket in _BRACKETED.findall(value):
        letters = re.sub(r"s$", "", re.sub(r"[^A-Za-z]", "", bracket)).lower()
        words = [w for w in re.split(r"[\s\-/]+", before) if w]
        if 2 <= len(letters) <= len(words) and "".join(w[0].lower() for w in words[-len(letters) :]) == letters:
            out.append(bracket)
    return out
_NEAR_AFTER = 40
_NEAR_BEFORE = 16


def _names(metric: str) -> list[str]:
    """The ways a metric's name can appear in a sentence: as written, without
    its parenthesised acronym, and as that acronym."""
    name = metric.strip().rstrip(".")
    bare = re.sub(r"\s*\([^)]*\)", "", name).strip()
    acronyms = _acronyms(name)
    return [n for n in dict.fromkeys([name, bare, *acronyms]) if n]


def _find(name: str, text: str) -> re.Match[str] | None:
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.IGNORECASE)


def _position(metric: str, text: str) -> tuple[int, int] | None:
    for n in _names(metric):
        m = _find(n, text)
        if m:
            return m.start(), m.end()
    return None


def reported_values(metrics: list[str], quote: str) -> dict[str, str]:
    """The value each metric is given in this one piece of evidence, when it
    unambiguously belongs to it. A metric the evidence names without a value
    of its own is left out."""
    out: dict[str, str] = {}
    present = {m: p for m in metrics if (p := _position(m, quote)) is not None}
    if not present:
        return out

    # "X and Y of 96% and 93% respectively": in order, when the counts agree
    resp = re.search(r"\brespectively\b", quote, re.IGNORECASE)
    if resp and len(present) >= 2:
        segment = quote[: resp.start()]
        named = sorted((p[0], m) for m, p in present.items() if p[1] <= resp.start())
        first = named[0][0] if named else 0
        values = [v.group(0).strip() for v in _VALUE.finditer(segment) if v.start() > first]
        if len(named) >= 2 and len(values) == len(named):
            return {m: v for (_pos, m), v in zip(named, values, strict=True)}

    others = list(present.values())

    def coordinated(start: int, end: int) -> bool:
        # "accuracy and F1 ... 91.2% and 0.88": names listed together share
        # their values in some order the sentence doesn't state
        return any(
            (o[1] <= start and len(quote[o[1] : start]) <= 12 and not _VALUE.search(quote[o[1] : start]))
            or (o[0] >= end and len(quote[end : o[0]]) <= 12 and not _VALUE.search(quote[end : o[0]]))
            for o in others
            if o != (start, end)
        )

    for metric, (start, end) in present.items():
        if coordinated(start, end):
            continue
        after = next((v for v in _VALUE.finditer(quote, end) if v.start() - end <= _NEAR_AFTER), None)
        if after and _in_series(quote, after):
            continue  # "from 44.5 to 47.1", "34.9%, 56.2% and 72.7%": not one result
        if after and not any(end <= o[0] < after.start() for o in others):
            out[metric] = after.group(0).strip()
            continue
        before = [v for v in _VALUE.finditer(quote, 0, start) if start - v.end() <= _NEAR_BEFORE]
        if before and not any(before[-1].end() <= o[0] < start for o in others):
            out[metric] = before[-1].group(0).strip()
    if not out and len(present) == 1:
        values = [v.group(0).strip() for v in _VALUE.finditer(quote)]
        if len(values) == 1:
            out[next(iter(present))] = values[0]
    return out


def _in_series(quote: str, value: re.Match[str]) -> bool:
    nxt = _VALUE.search(quote, value.end())
    return nxt is not None and _CONNECTOR.fullmatch(quote[value.end() : nxt.start()]) is not None


def _normalized(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _with_values(metrics: ProfileList) -> ProfileList:
    by_quote: dict[str, list[ProfileField]] = {}
    for item in metrics.items:
        span = item.source_span
        if item.status is ProvenanceStatus.VERIFIED and span is not None and span.quote:
            by_quote.setdefault(span.quote, []).append(item)
    derived: dict[int, str] = {}
    for quote, items in by_quote.items():
        found = reported_values([i.value for i in items], quote)
        for i in items:
            if i.value in found:
                derived[id(i)] = found[i.value]
    out: list[ProfileField] = []
    for item in metrics.items:
        rv = item.reported_value
        if rv is not None:
            # a value counts as the paper's only when it is written in the metric's own verified evidence
            span = item.source_span
            written = item.status is ProvenanceStatus.VERIFIED and span is not None and _normalized(rv.text) in _normalized(span.quote)
            status = ProvenanceStatus.VERIFIED if written else ProvenanceStatus.UNVERIFIED
            if status is not rv.status:
                rv = ReportedValue(text=rv.text, status=status)
        if rv is None and id(item) in derived:
            rv = ReportedValue(text=derived[id(item)], status=ProvenanceStatus.VERIFIED)
        out.append(item if rv is item.reported_value else item.model_copy(update={"reported_value": rv}))
    return ProfileList(items=out)


# --- how a value reads ------------------------------------------------------

_FIRST_WORD = re.compile(r"[a-z][a-z'\-]*")
_TRAILING_STOP = re.compile(r"(?<!\betc)(?<!\bal)\.$")
_QUESTION = re.compile(r"^(?:what|how|why|which|who|when|where|can|could|does|do|is|are|will|would|should|to what)\b", re.I)


def _sentence_case(value: str) -> str:
    first = value.split(" ", 1)[0]
    # "precision" -> "Precision"; "k-means", "face-api.js", "word2vec", "iPhone" stay as written
    if _FIRST_WORD.fullmatch(first) and not re.match(r"^[a-z]-", first):
        return value[0].upper() + value[1:]
    return value


def _name(value: str) -> str:
    """A name or short phrase: one line, sentence case, no full stop."""
    v = _sentence_case(clean_text(value))
    if len(v.split()) <= 12 and ". " not in v:
        v = _TRAILING_STOP.sub("", v)
    return v


def _statement(value: str, *, question: bool = False) -> str:
    """A sentence: capitalised, and ended."""
    v = _sentence_case(clean_text(value))
    if v and (v[-1].isalnum() or v.endswith(")")):
        v += "?" if question and _QUESTION.match(v) else "."
    return v


def _reword(field: ProfileField, fix) -> ProfileField:  # noqa: ANN001 - a str -> str function
    if field.status is ProvenanceStatus.USER_EDITED or not field.value:
        return field
    value = fix(field.value)
    return field if value == field.value else field.model_copy(update={"value": value})


# --- one thing, listed once --------------------------------------------------

_GENERIC = {
    "a", "an", "the", "of", "for", "using", "use", "based", "method", "approach", "technique", "algorithm", "model",
    "framework", "system", "technology", "dataset", "data", "set", "metric", "score",
}


def item_keys(value: str) -> set[str]:
    """What makes two items the same thing: their words without case,
    punctuation, plural endings or generic head nouns -- and, for a name
    with its acronym in brackets, that acronym too."""
    keys: set[str] = set()
    for acronym in _acronyms(value):
        a = acronym.lower()
        keys.add(a[:-1] if len(a) > 3 and a.endswith("s") else a)
    text = re.sub(r"\([^)]*\)", " ", value.lower())
    words = [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in re.findall(r"[a-z0-9]+", text)]
    core = [w for w in words if w not in _GENERIC] or words
    if core:
        keys.add(" ".join(core))
    return keys


def _prefer(a: ProfileField, b: ProfileField) -> ProfileField:
    """Of two copies of one item, the one with evidence."""
    rank = {ProvenanceStatus.USER_EDITED: 2, ProvenanceStatus.VERIFIED: 1, ProvenanceStatus.UNVERIFIED: 0}
    return b if rank[b.status] > rank[a.status] else a


def _dedupe(items: Iterable[ProfileField], *, taken: set[str], with_value: bool = False) -> list[ProfileField]:
    kept: list[tuple[set[str], ProfileField]] = []
    for item in items:
        keys = item_keys(item.value)
        if with_value and item.reported_value is not None:
            keys = {f"{k}={_normalized(item.reported_value.text)}" for k in keys}
        if item.status is not ProvenanceStatus.USER_EDITED and keys & taken:
            continue
        twin = next((i for i, (k, _f) in enumerate(kept) if k & keys), None)
        if twin is None:
            kept.append((keys, item))
        else:
            k, f = kept[twin]
            kept[twin] = (k | keys, _prefer(f, item))
    return [f for _k, f in kept]


# the more specific a heading, the earlier: an item listed under one leaves the later ones
_PRECEDENCE = ("models", "algorithms", "datasets", "methods", "cited_methods")
_NAMES = ("subdomains", "methods", "models", "algorithms", "datasets", "evaluation_metrics", "important_entities", "cited_methods")
_STATEMENTS = ("objectives", "findings", "limitations", "future_work")


def refine_profile(profile: ResearchProfile, *, abstract_found: bool | None = None) -> ResearchProfile:
    """The profile, cleaned, summarised and deduplicated (see module docstring).
    Idempotent: refining a refined profile changes nothing."""
    found = profile.abstract_found if abstract_found is None else abstract_found
    abstract = clean_abstract(profile.abstract) or profile.abstract
    updates: dict[str, object] = {
        "abstract": abstract,
        "abstract_found": found,
        "summary": summarize(abstract) if found else "",
        "domain": _reword(profile.domain, _name),
        "research_problem": _reword(profile.research_problem, _statement),
        "research_questions": ProfileList(
            items=[_reword(i, lambda v: _statement(v, question=True)) for i in profile.research_questions.items]
        ),
    }
    for attr in _STATEMENTS:
        lst: ProfileList = getattr(profile, attr)
        updates[attr] = ProfileList(items=_dedupe((_reword(i, _statement) for i in lst.items), taken=set()))
    named = {attr: [_reword(i, _name) for i in getattr(profile, attr).items] for attr in _NAMES}
    named["evaluation_metrics"] = _with_values(ProfileList(items=named["evaluation_metrics"])).items

    updates["evaluation_metrics"] = ProfileList(items=_dedupe(named["evaluation_metrics"], taken=set(), with_value=True))
    taken: set[str] = set()
    for attr in _PRECEDENCE:
        kept = _dedupe(named[attr], taken=taken)
        updates[attr] = ProfileList(items=kept)
        taken |= _keys_of(kept)
    # subdomains name the field, not a thing the paper used: only the domain itself repeats one
    domain = updates["domain"]
    assert isinstance(domain, ProfileField)
    domain_keys = item_keys(domain.value) if domain.value else set()
    subdomains = _dedupe(named["subdomains"], taken=domain_keys)
    updates["subdomains"] = ProfileList(items=subdomains)
    # an entity already shown anywhere else -- a method, the field, a keyword -- is a repeat
    seen = taken | domain_keys | _keys_of(subdomains) | {k for kw in profile.keywords for k in item_keys(kw)}
    updates["important_entities"] = ProfileList(items=_dedupe(named["important_entities"], taken=seen))
    return profile.model_copy(update=updates)


def _keys_of(items: list[ProfileField]) -> set[str]:
    return {k for item in items for k in item_keys(item.value)}
