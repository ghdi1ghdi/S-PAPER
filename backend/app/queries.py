import re


def build_queries(topic, keywords, overrides=None):
    # Preserve quoted topic phrases; keywords containing spaces are explicit phrases.
    terms = []
    for keyword in keywords:
        clean = " ".join(keyword.strip().strip('"').split())
        if clean and clean.casefold() not in [x.casefold() for x in terms]:
            terms.append(clean)
    remainder = topic
    for term in sorted(terms, key=len, reverse=True):
        remainder = re.sub(r"(?<!\w)" + re.escape(term) + r"(?!\w)", " ", remainder, flags=re.I)
    extras = [x.strip('"') for x in re.findall(r'"[^"]+"|[^\s"]+', remainder)]
    terms += [x for x in extras if x and x.casefold() not in [t.casefold() for t in terms]]
    scholar = topic.strip()
    for term in terms:
        if not re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", scholar, re.I):
            scholar += " " + (f'"{term}"' if " " in term else term)
    arxiv = " AND ".join('all:' + (f'"{t}"' if " " in t else '"' + t + '"' if re.search(r'[^\w-]', t) else t) for t in terms)
    return {"google_scholar": " ".join(scholar.split()), "arxiv": arxiv} | (overrides or {})
