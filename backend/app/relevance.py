"""Topic relevance of a candidate, scored from its title and abstract (or Scholar snippet).

Search engines return loosely matching results (arXiv especially), and the collector used to
store them in arrival order until the goal was reached. Each page is now enriched first, then
ranked by this score, and candidates under settings.relevance_min_score are skipped.

Score in [0, 1]:
  0.75 x weighted share of the topic's concepts found (a title hit weighs 1.0, abstract-only 0.7)
+ 0.25 x 1 if any extra keyword (keywords outside the topic) appears, else 0
A multi-word concept counts fully as an exact phrase, 0.8 when all its words appear separately.
With no extra keywords the topic share takes the full weight.
"""
import re
import unicodedata
from .queries import split_terms

STOP = {"a", "an", "and", "the", "of", "for", "in", "on", "with", "to", "by", "using", "via", "from", "or"}


def stem(token):
    """Tiny English stemmer: plural and -ing/-ed forms map to one key (spindles/spindle, detected/detect)."""
    if len(token) <= 3:
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith(("sses", "xes", "ches", "shes")):
        return token[:-2]
    if token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    for suffix in ("ing", "ed"):
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            base = token[: -len(suffix)]
            return base[:-1] if len(base) > 2 and base[-1] == base[-2] else base
    return token


def tokens(value):
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return [stem(t) for t in re.findall(r"\w+", value)]


def concept_hit(concept, words, joined):
    parts = [t for t in tokens(concept) if t not in STOP] or tokens(concept)
    if not parts:
        return 0.0
    if " " + " ".join(parts) + " " in joined:
        return 1.0
    present = set(words)
    if all(p in present for p in parts):
        return 0.8 if len(parts) > 1 else 1.0
    return 0.0


def relevance_score(topic, keywords, title, body):
    core, extras = split_terms(topic, keywords)
    if not core and not extras:
        return 1.0
    title_words, body_words = tokens(title), tokens(body)
    title_joined = " " + " ".join(title_words) + " "
    body_joined = " " + " ".join(body_words) + " "

    def hit(concept):
        return max(concept_hit(concept, title_words, title_joined),
                   0.7 * concept_hit(concept, body_words, body_joined))

    core_share = sum(hit(c) for c in core) / len(core) if core else 0.0
    extra_hit = 1.0 if any(hit(e) for e in extras) else 0.0
    if not core:
        return round(extra_hit, 3)
    if not extras:
        return round(core_share, 3)
    return round(0.75 * core_share + 0.25 * extra_hit, 3)


def candidate_relevance(topic, keywords, candidate):
    return relevance_score(topic, keywords, candidate.title, candidate.abstract or candidate.search_snippet or "")
