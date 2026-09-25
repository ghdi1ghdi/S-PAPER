import pytest
from app.providers.publisher import resolve_public, fetch_html
from app.providers.base import ProviderError


@pytest.mark.parametrize('ip',['127.0.0.1','10.1.2.3','169.254.169.254','::1','fc00::1'])
def test_ssrf_private_ips(monkeypatch,ip):
    monkeypatch.setattr('socket.getaddrinfo',lambda *a,**k:[(0,0,0,'',(ip,443))])
    with pytest.raises(ProviderError,match='UNSAFE_URL'):
        resolve_public('publisher.example')


@pytest.mark.parametrize('url',['http://publisher.example','https://localhost','https://publisher.example:8080','https://user:pass@publisher.example'])
def test_publisher_url_constraints(url):
    with pytest.raises(ProviderError,match='UNSAFE_URL'):
        fetch_html(url,{'publisher.example'})
