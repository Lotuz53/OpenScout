import pytest

from docsgpt.core.cors import (
    DEFAULT_CORS_ALLOWED_ORIGINS,
    cors_allowed_origins,
    is_allowed_cors_origin,
    is_loopback_client,
    parse_cors_allowed_origins,
)


@pytest.mark.unit
def test_unconfigured_origins_use_local_frontend_defaults():
    assert parse_cors_allowed_origins(None) == DEFAULT_CORS_ALLOWED_ORIGINS
    assert cors_allowed_origins(None, None) == DEFAULT_CORS_ALLOWED_ORIGINS


@pytest.mark.unit
def test_origins_are_exact_and_non_loopback_requires_secure_auth():
    configured = "https://app.example, http://localhost:5173"

    assert is_allowed_cors_origin("http://localhost:5173", configured, None)
    assert not is_allowed_cors_origin("http://localhost:5173/", configured, None)
    assert not is_allowed_cors_origin("https://app.example", configured, None)
    assert is_allowed_cors_origin("https://app.example", configured, "oidc")


@pytest.mark.unit
def test_wildcard_origin_is_rejected():
    with pytest.raises(ValueError, match="wildcard"):
        parse_cors_allowed_origins("*")


@pytest.mark.unit
def test_loopback_client_detection_rejects_remote_addresses():
    assert is_loopback_client("127.0.0.1")
    assert is_loopback_client("::1")
    assert not is_loopback_client("198.51.100.10")
    assert not is_loopback_client(None)
