import re

STOP = {"a", "an", "and", "the", "of", "for", "in", "on", "with", "to", "by", "using", "via", "from", "or"}


def _clean(keyword):
    return " ".join(keyword.strip().strip('"').split())


def split_terms(topic, keywords):
    """Return (core, extras).

    core: the topic's concepts, all required — keywords that occur in the topic stay one phrase,
    the remaining topic words (or "quoted phrases") become single concepts.
    extras: keywords not in the topic; at least one of them should match (OR group).
    """
    keys = []
    for keyword in keywords:
        clean = _clean(keyword)
        if clean and clean.casefold() not in [x.casefold() for x in keys]:
            keys.append(clean)
    in_topic = [k for k in keys if re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", topic, re.I)]
    extras = [k for k in keys if k not in in_topic]
    remainder = topic
    for term in sorted(in_topic, key=len, reverse=True):
        remainder = re.sub(r"(?<!\w)" + re.escape(term) + r"(?!\w)", " ", remainder, flags=re.I)
    leftovers = [x.strip('"') for x in re.findall(r'"[^"]+"|[^\s"]+', remainder)]
    core = list(in_topic)
    for word in leftovers:
        if word and word.casefold() not in STOP and word.casefold() not in [c.casefold() for c in core]:
            core.append(word)
    return core, extras


def _quote(term):
    return f'"{term}"' if re.search(r"[^\w-]", term) else term


def build_queries(topic, keywords, overrides=None):
    core, extras = split_terms(topic, keywords)
    # Scholar: the topic as typed (no forced phrase quotes, Scholar ranks by relevance itself),
    # plus the extra keywords as one OR group so synonyms widen recall instead of narrowing it.
    scholar = topic.strip()
    if len(extras) == 1:
        scholar += " " + _quote(extras[0])
    elif extras:
        scholar += " (" + " OR ".join(_quote(e) for e in extras) + ")"
    # arXiv: each core concept must be in the title or abstract; extras form one OR group.
    field = lambda t: f"(ti:{_quote(t)} OR abs:{_quote(t)})"
    clauses = [field(c) for c in core]
    if len(extras) == 1:
        clauses.append(field(extras[0]))
    elif extras:
        clauses.append("(" + " OR ".join(f"ti:{_quote(e)} OR abs:{_quote(e)}" for e in extras) + ")")
    arxiv = " AND ".join(clauses)
    return {"google_scholar": " ".join(scholar.split()), "arxiv": arxiv} | (overrides or {})
