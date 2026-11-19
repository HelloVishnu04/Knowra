import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

from app.core.config import settings


class ProviderEgressError(ValueError):
    """Raised when a provider destination violates the outbound network policy."""


def private_host_allowlist(value: str | None = None) -> set[str]:
    configured = settings.PROVIDER_PRIVATE_HOST_ALLOWLIST if value is None else value
    return {
        host.strip().lower().rstrip(".")
        for host in configured.split(",")
        if host.strip()
    }


def address_is_private(address: str) -> bool:
    parsed = ipaddress.ip_address(address)
    if parsed.version == 6 and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    return not parsed.is_global


def validate_provider_url_policy(
    base_url: str,
    *,
    block_private: bool | None = None,
    allowed_private_hosts: set[str] | None = None,
) -> None:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Provider URL must use HTTP or HTTPS")
    if parsed.username or parsed.password:
        raise ValueError("Provider URL must not contain credentials")
    hostname = parsed.hostname.lower().rstrip(".")
    allowlist = (
        private_host_allowlist()
        if allowed_private_hosts is None
        else {host.lower().rstrip(".") for host in allowed_private_hosts}
    )
    if hostname in allowlist:
        return
    should_block = (
        settings.PROVIDER_BLOCK_PRIVATE_NETWORKS
        if block_private is None
        else block_private
    )
    if not should_block:
        return
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ProviderEgressError("Provider URL targets a private or local network")
    try:
        parsed_address = ipaddress.ip_address(hostname)
    except ValueError:
        return  # A DNS name is checked immediately before each outbound request.
    if address_is_private(str(parsed_address)):
        raise ProviderEgressError("Provider URL targets a private or local network")


async def assert_provider_egress_allowed(base_url: str) -> None:
    validate_provider_url_policy(base_url)
    if not settings.PROVIDER_BLOCK_PRIVATE_NETWORKS:
        return
    parsed = urlsplit(base_url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if hostname in private_host_allowlist():
        return
    try:
        ipaddress.ip_address(hostname)
        return  # Direct IP literals were checked by validate_provider_url_policy.
    except ValueError:
        pass
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            port,
            socket.AF_UNSPEC,
            socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ProviderEgressError("Provider hostname could not be resolved") from exc
    resolved = {str(item[4][0]) for item in addresses}
    if not resolved:
        raise ProviderEgressError("Provider hostname did not resolve to an address")
    if any(address_is_private(address) for address in resolved):
        raise ProviderEgressError(
            "Provider hostname resolves to a private or local network"
        )


def normalize_provider_url(provider_type: str, base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    parsed = urlsplit(value)
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    host = hostname

    if provider_type in {"lm_studio", "ollama"} and hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        host = "host.docker.internal"

    path = parsed.path.rstrip("/")
    if provider_type == "lm_studio" and not path:
        path = "/v1"
    if provider_type == "google_gemini":
        return "https://generativelanguage.googleapis.com/v1beta/openai"

    netloc = f"{host}{port}"
    return urlunsplit((parsed.scheme, netloc, path, parsed.query, ""))
