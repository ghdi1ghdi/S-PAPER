import hashlib
import logging
import json
import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import httpx
import redis
from ..config import settings
from .base import ProviderError

# Workers import this module without FastAPI: suppress credential-bearing SDK/HTTP URLs here too.
for logger_name in ("httpx", "httpcore", "openai", "google.genai"):
    logging.getLogger(logger_name).disabled = True


class HTTPGateway:
    def __init__(self, usage=None, deadline=None, client=None, cache=None, on_usage=None):
        self.cfg = settings()
        self.usage = usage if usage is not None else {}
        self.deadline = deadline or time.monotonic() + self.cfg.max_job_seconds
        self.client = client or httpx.Client(timeout=self.cfg.http_timeout_seconds, follow_redirects=False, trust_env=False)
        self.cache = cache if cache is not None else redis.Redis.from_url(self.cfg.redis_url)
        self.on_usage = on_usage or (lambda: None)

    def increment(self, source, key, count=1):
        entry = self.usage.setdefault(source, {})
        entry[key] = entry.get(key, 0) + count
        self.on_usage()

    def wait(self, seconds):
        if time.monotonic() + seconds >= self.deadline:
            raise ProviderError("TIME_BUDGET")
        time.sleep(seconds)

    def throttle(self, source):
        interval = {"arxiv": 3.05, "crossref": 1.0, "openalex": 0.12, "europepmc": 0.2,
                    "semantic_scholar": 1.05}.get(source)
        if not interval:
            return
        # Redis atomic slot reservation shares spacing across every worker and every retry.
        while True:
            if time.monotonic() >= self.deadline:
                raise ProviderError("TIME_BUDGET")
            if self.cache.set(f"rate:{source}", "1", nx=True, px=int(interval * 1000)):
                return
            self.wait(0.15)

    def get(self, source, url, params, ttl=3600, headers=None):
        key_params = {k: v for k, v in params.items() if k != "api_key"}
        cache_key = "http:" + hashlib.sha256(json.dumps([source, url, key_params], sort_keys=True).encode()).hexdigest()
        cached = self.cache.get(cache_key)
        if cached:
            self.increment(source, "cache_hits")
            return cached.decode() if isinstance(cached, bytes) else cached
        for attempt in range(self.cfg.max_http_attempts):
            if time.monotonic() >= self.deadline:
                raise ProviderError("TIME_BUDGET")
            if source == "google_scholar" and self.usage.get(source, {}).get("requests", 0) >= self.cfg.max_serpapi_requests_per_job:
                raise ProviderError("CALL_BUDGET")
            self.throttle(source)
            self.increment(source, "requests")
            try:
                response = self.client.get(url, params=params, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError):
                self.increment(source, "errors")
                if attempt + 1 == self.cfg.max_http_attempts:
                    raise ProviderError("TIMEOUT_OR_NETWORK") from None
                self.increment(source, "retries")
                self.wait(2 ** attempt + random.random())
                continue
            status = response.status_code
            body = response.text
            if status in (401, 403):
                self.increment(source, "errors")
                raise ProviderError("AUTHORIZATION_ERROR")
            exhausted = any(x in body.lower() for x in ("run out of searches", "searches exhausted", "monthly quota", "insufficient credits"))
            if exhausted:
                self.increment(source, "errors")
                raise ProviderError("QUOTA_EXHAUSTED")
            if status == 429 or status >= 500:
                self.increment(source, "errors")
                code = "RATE_LIMIT" if status == 429 else "UPSTREAM_ERROR"
                if attempt + 1 == self.cfg.max_http_attempts:
                    raise ProviderError(code)
                delay = 2 ** attempt + random.random()
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        try:
                            delay = max(delay, (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds())
                        except (ValueError, TypeError):
                            pass
                self.increment(source, "retries")
                self.wait(delay)
                continue
            if status == 404:
                raise ProviderError("NOT_FOUND")
            if status != 200:
                raise ProviderError("HTTP_ERROR")
            if len(response.content) > 8_000_000:
                raise ProviderError("RESPONSE_TOO_LARGE")
            # Never cache error payloads (even HTTP 200).
            if source != "arxiv":
                try:
                    data = response.json()
                except ValueError:
                    raise ProviderError("INVALID_JSON") from None
                if not isinstance(data, dict):
                    raise ProviderError("SCHEMA_ERROR")
                if data.get("error"):
                    if str(data["error"]).startswith("Google hasn't returned any results"):
                        return body
                    self.increment(source, "errors")
                    raise ProviderError("UPSTREAM_BODY_ERROR")
                if isinstance(data.get("search_metadata"), dict) and data["search_metadata"].get("status") in ("Error", "Failed"):
                    raise ProviderError("UPSTREAM_BODY_ERROR")
            self.cache.setex(cache_key, ttl, body)
            return body
        raise ProviderError("RETRY_EXHAUSTED")

    def close(self):
        self.client.close()
