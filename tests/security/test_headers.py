"""Tests for shared security response headers."""

from docsgpt.security.headers import apply_security_headers


def test_route_specific_security_headers_are_not_replaced_or_duplicated():
    headers = {
        "x-content-type-options": "route-value",
        "Content-Security-Policy": "route-policy",
    }

    apply_security_headers(headers, is_https=True)

    assert headers["x-content-type-options"] == "route-value"
    assert headers["Content-Security-Policy"] == "route-policy"
    assert "Strict-Transport-Security" in headers
    assert "X-Content-Type-Options" not in headers
