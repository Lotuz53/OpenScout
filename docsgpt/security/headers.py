"""Shared security response headers for Flask and ASGI responses."""

from collections.abc import MutableMapping


_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'self'; "
    "form-action 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https:; "
    "font-src 'self' data: https:; "
    "connect-src 'self' https: wss:; "
    "media-src 'self' data: blob:; "
    "worker-src 'self' blob:; "
    "manifest-src 'self'"
)

_BASE_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=(self)",
    "Content-Security-Policy": _CONTENT_SECURITY_POLICY,
}


def apply_security_headers(headers: MutableMapping[str, str], *, is_https: bool) -> None:
    """Add baseline security headers without replacing route-specific values."""
    existing_names = {name.lower() for name in headers.keys()}
    for name, value in _BASE_SECURITY_HEADERS.items():
        if name.lower() not in existing_names:
            headers[name] = value
            existing_names.add(name.lower())
    if is_https and "strict-transport-security" not in existing_names:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
