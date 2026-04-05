import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_extract_quick_tunnel_url_returns_valid_random_subdomain():
    import tunnel_manager

    line = "INF +------------------------------------------------------------+ https://alpha-signal-desk.trycloudflare.com"
    assert tunnel_manager._extract_quick_tunnel_url(line) == "https://alpha-signal-desk.trycloudflare.com"


def test_extract_quick_tunnel_url_ignores_generic_api_host():
    import tunnel_manager

    line = "INF Requesting new quick Tunnel on https://api.trycloudflare.com"
    assert tunnel_manager._extract_quick_tunnel_url(line) is None


def test_cloudflared_command_uses_http2_and_loopback(monkeypatch):
    import tunnel_manager

    monkeypatch.setattr(tunnel_manager, "_PROTOCOL", "http2")
    monkeypatch.setattr(tunnel_manager, "_PORT", 8501)
    assert tunnel_manager._cloudflared_command() == [
        "cloudflared",
        "tunnel",
        "--protocol",
        "http2",
        "--url",
        "http://127.0.0.1:8501",
    ]
