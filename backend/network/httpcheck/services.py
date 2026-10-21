"""HTTP endpoint monitoring: a bounded GET probe against a configured URL.

This runs alongside ICMP monitoring. ICMP answers "is the host there?", the
HTTP probe answers "is the service there and is it answering in time?" — the
two routinely disagree, so they are recorded independently.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

DEFAULT_HTTP_TIMEOUT_SECONDS = 5.0
MAX_HTTP_TIMEOUT_SECONDS = 30.0
ALLOWED_SCHEMES = ("http", "https")
PROBE_USER_AGENT = "NetWatch-Monitor/1.0"
# Cap how much of the body we pull so a huge or streaming response cannot stall
# the probe after the headers arrive.
PROBE_BODY_BYTES = 1024


class HTTPMonitoringError(Exception):
    """Base exception for expected HTTP monitoring errors."""


class InvalidHTTPConfiguration(HTTPMonitoringError):
    """Raised when the configured endpoint cannot be probed at all."""


@dataclass(frozen=True)
class HTTPCheckResult:
    ok: bool
    status_code: int | None
    response_time_ms: float | None
    error: str | None = None


def validate_endpoint_url(url: str) -> str:
    """Return the normalised endpoint URL or raise for an unusable one."""
    value = (url or "").strip()
    if not value:
        raise InvalidHTTPConfiguration("An HTTP endpoint URL is required.")

    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise InvalidHTTPConfiguration("The HTTP endpoint must use http:// or https://.")
    if not parsed.netloc or not parsed.hostname:
        raise InvalidHTTPConfiguration("The HTTP endpoint URL must include a host.")
    if parsed.username or parsed.password:
        raise InvalidHTTPConfiguration("The HTTP endpoint URL must not embed credentials.")
    return value


def _is_expected(status_code: int, expected_status: int | None) -> bool:
    if expected_status is None:
        return 200 <= status_code < 400
    return status_code == expected_status


def _elapsed_ms(started: float) -> float:
    return round((time.monotonic() - started) * 1000, 3)


def check_http_endpoint(
    url: str,
    timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    expected_status: int | None = None,
) -> HTTPCheckResult:
    """Perform one bounded GET request without invoking a shell."""
    endpoint = validate_endpoint_url(url)

    try:
        timeout = float(timeout_seconds)
    except (TypeError, ValueError) as exc:
        raise InvalidHTTPConfiguration("HTTP timeout must be a number.") from exc
    if timeout <= 0:
        raise InvalidHTTPConfiguration("HTTP timeout must be greater than zero.")
    timeout = min(timeout, MAX_HTTP_TIMEOUT_SECONDS)

    request = urllib.request.Request(
        endpoint,
        method="GET",
        headers={"User-Agent": PROBE_USER_AGENT},
    )
    started = time.monotonic()

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            # Read a bounded slice so the connection closes promptly.
            response.read(PROBE_BODY_BYTES)
            status_code = response.getcode()
    except urllib.error.HTTPError as exc:
        # An HTTP error status is still a delivered response, so latency is known.
        elapsed = _elapsed_ms(started)
        status_code = exc.code
        if _is_expected(status_code, expected_status):
            return HTTPCheckResult(True, status_code, elapsed)
        return HTTPCheckResult(False, status_code, elapsed, f"Endpoint returned HTTP {status_code}.")
    except TimeoutError:
        return HTTPCheckResult(False, None, None, "HTTP request timed out.")
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError):
            return HTTPCheckResult(False, None, None, "HTTP request timed out.")
        return HTTPCheckResult(False, None, None, f"HTTP request failed: {reason or exc}")
    except OSError as exc:
        return HTTPCheckResult(False, None, None, f"HTTP network error: {exc}")

    elapsed = _elapsed_ms(started)
    if not _is_expected(status_code, expected_status):
        return HTTPCheckResult(False, status_code, elapsed, f"Endpoint returned HTTP {status_code}.")
    return HTTPCheckResult(True, status_code, elapsed)
