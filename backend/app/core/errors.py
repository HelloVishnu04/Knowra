from typing import Any

STATUS_CODES: dict[int, tuple[str, bool]] = {
    400: ("bad_request", False),
    401: ("authentication_required", False),
    403: ("permission_denied", False),
    404: ("not_found", False),
    409: ("conflict", False),
    413: ("payload_too_large", False),
    415: ("unsupported_media_type", False),
    422: ("validation_failed", False),
    429: ("rate_limited", True),
    500: ("internal_error", True),
    502: ("upstream_error", True),
    503: ("service_unavailable", True),
    504: ("upstream_timeout", True),
}


def error_payload(
    status_code: int,
    detail: Any,
    correlation_id: str,
    *,
    code: str | None = None,
    retryable: bool | None = None,
) -> dict[str, Any]:
    default_code, default_retryable = STATUS_CODES.get(
        status_code, ("request_failed", status_code >= 500)
    )
    message = detail if isinstance(detail, str) else "Request validation failed"
    return {
        # Retain FastAPI's detail field while clients migrate to the stable envelope.
        "detail": detail,
        "error": {
            "code": code or default_code,
            "message": message,
            "retryable": default_retryable if retryable is None else retryable,
            "correlation_id": correlation_id,
        },
    }
