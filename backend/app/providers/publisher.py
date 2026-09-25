"""Opt-in publisher metadata; only allowlisted public hosts, pinned DNS, bounded HTML reads."""
import ipaddress
import socket
import time
import httpx
from urllib.parse import urlsplit, urljoin
from bs4 import BeautifulSoup
from .base import ProviderError, normalize_doi, norm_title
from .enrichment import clean_abstract
from ..db import now


def resolve_public(host):
    addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ProviderError("UNSAFE_URL")
    return sorted(addresses)[0]


def fetch_html(url, allowed_hosts, timeout=10, max_bytes=1_000_000):
    deadline = time.monotonic() + timeout
    for _ in range(4):
        u = urlsplit(url)
        if u.scheme != "https" or u.username or u.password or u.port not in (None, 443) or u.hostname not in allowed_hosts:
            raise ProviderError("UNSAFE_URL")
        ip = resolve_public(u.hostname)
        if time.monotonic() >= deadline:
            raise ProviderError("TIME_BUDGET")
        # Pin the validated IP for the actual connection (DNS rebinding resistant), retain TLS SNI.
        target = httpx.URL(url).copy_with(host=ip)
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=max(0.1, deadline - time.monotonic())) as client:
            with client.stream("GET", target, headers={"Host": u.hostname, "User-Agent": "S-PAPER/0.1"},
                               extensions={"sni_hostname": u.hostname}) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers.get("location", ""))
                    continue
                if response.status_code != 200 or "text/html" not in response.headers.get("content-type", ""):
                    return None
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes or time.monotonic() >= deadline:
                        raise ProviderError("RESPONSE_LIMIT")
                    chunks.append(chunk)
                return b"".join(chunks).decode("utf-8", errors="replace")
    raise ProviderError("REDIRECT_LIMIT")


class PublisherMetadataEnricher:
    def __init__(self, hosts):
        self.hosts = set(filter(None, [x.strip() for x in hosts.split(",")]))

    def enrich(self, c):
        urls = [c.source_url] + [x.get("link") for x in c.raw.get("resources", []) if isinstance(x, dict)]
        for url in urls[:3]:
            if not url or urlsplit(url).hostname not in self.hosts:
                continue
            body = fetch_html(url, self.hosts)
            if not body:
                continue
            soup = BeautifulSoup(body, "html.parser")
            meta = {x.get("name", x.get("property", "")).lower(): x.get("content", "") for x in soup.find_all("meta")}
            title = meta.get("citation_title") or meta.get("dc.title")
            doi = normalize_doi(meta.get("citation_doi") or meta.get("dc.identifier"))
            if not title or norm_title(title) != norm_title(c.title) or (c.doi and doi and c.doi != doi):
                continue
            for field, value in (("doi", doi), ("abstract", clean_abstract(meta.get("citation_abstract") or meta.get("dc.description"))),
                                 ("journal", meta.get("citation_journal_title"))):
                if value and not getattr(c, field):
                    setattr(c, field, value)
                    c.provenance[field] = {"source": url, "retrieved_at": now().isoformat(), "basis": "exact citation_title match"}
        return c
