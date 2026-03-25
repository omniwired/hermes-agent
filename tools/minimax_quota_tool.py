"""MiniMax Quota Tool - Fetch current API quota usage."""

import json
import logging
import requests

logger = logging.getLogger(__name__)

# Endpoints
MINIMAX_QUOTA_URL = "https://api.minimax.io/v1/coding_plan/remains"
MINIMAX_CN_QUOTA_URL = "https://api.minimaxi.com/v1/coding_plan/remains"


def _get_minimax_api_key() -> str:
    """Get MiniMax API key from hermes secret storage (env vars or ~/.hermes/.env)."""
    from hermes_cli.config import get_env_value
    return get_env_value("MINIMAX_API_KEY") or ""


def _get_minimax_cn_api_key() -> str:
    """Get MiniMax China API key from hermes secret storage (env vars or ~/.hermes/.env)."""
    from hermes_cli.config import get_env_value
    return get_env_value("MINIMAX_CN_API_KEY") or ""


def _is_standard_key(api_key: str) -> bool:
    """Check if key is a standard MiniMax key (sk-api-*).

    Standard keys are tied to web sessions and do NOT work with the direct API.
    Only coding plan keys (sk-cp-*) or service keys work with /v1/coding_plan/remains.
    """
    return api_key.startswith("sk-api-")


def _detect_key_kind(api_key: str) -> str:
    """Detect the type of MiniMax API key."""
    if api_key.startswith("sk-cp-"):
        return "coding_plan"
    elif api_key.startswith("sk-api-"):
        return "standard"
    elif api_key.startswith("sk-"):
        return "service"
    return "unknown"


def check_minimax_quota_requirements() -> bool:
    """Check if MiniMax API key is configured (either global or China)."""
    return bool(_get_minimax_api_key() or _get_minimax_cn_api_key())


def _fetch_quota(api_key: str, base_url: str) -> dict:
    """Make the quota API request."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    resp = requests.get(base_url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _format_quota_response(data: dict, provider_label: str) -> str:
    """Format quota data for display."""
    total = data.get("current_interval_total_count", 0)
    used = data.get("current_interval_usage_count", 0)
    remaining = total - used
    start = data.get("start_time", "unknown")
    end = data.get("end_time", "unknown")

    # Calculate percentage
    pct = (used / total * 100) if total > 0 else 0

    lines = [
        f"  {provider_label} Quota",
        f"  {'─' * 40}",
        f"  Total:     {total:,}",
        f"  Used:      {used:,} ({pct:.1f}%)",
        f"  Remaining: {remaining:,}",
        f"  Period:    {start} → {end}",
    ]
    return "\n".join(lines)


def minimax_quota_tool(provider: str = "auto") -> str:
    """
    Fetch MiniMax API quota information.

    Args:
        provider: Which MiniMax provider to check:
            - "auto" (default): try global first, fall back to China
            - "minimax": use international endpoint (api.minimax.io)
            - "minimax-cn": use China endpoint (api.minimaxi.com)

    Returns:
        JSON string with quota details or error message.
    """
    def _check_and_fetch(api_key: str, base_url: str, provider_label: str) -> str | None:
        """Check key type and fetch quota. Returns None on error, error JSON on failure."""
        key_kind = _detect_key_kind(api_key)
        if key_kind == "standard":
            return json.dumps({
                "error": (
                    "Standard MiniMax API keys (sk-api-*) do not work with the quota API endpoint. "
                    "You need a coding plan key (sk-cp-*) or service key. "
                    "See: https://platform.minimax.io/user-center/payment/coding-plan"
                ),
                "key_kind": "standard",
            })
        if key_kind == "unknown":
            return json.dumps({
                "error": (
                    "Unrecognized MiniMax API key format. "
                    "This tool requires a coding plan key (sk-cp-*) or service key."
                ),
                "key_kind": "unknown",
            })
        try:
            data = _fetch_quota(api_key, base_url)
            return json.dumps({
                "provider": provider_label,
                "data": data,
                "formatted": _format_quota_response(data, provider_label),
            })
        except Exception as e:
            logger.warning("Failed to fetch %s quota: %s", provider_label, e)
            return None

    if provider == "auto":
        # Try global first, then China
        api_key = _get_minimax_api_key()
        if api_key:
            result = _check_and_fetch(api_key, MINIMAX_QUOTA_URL, "MiniMax (Global)")
            if result:
                return result
            # If result is None, API failed - try China as fallback

        # Fall back to China
        api_key = _get_minimax_cn_api_key()
        if api_key:
            result = _check_and_fetch(api_key, MINIMAX_CN_QUOTA_URL, "MiniMax (China)")
            if result:
                return result
            return json.dumps({"error": f"Failed to fetch MiniMax CN quota"})

        return json.dumps({"error": "No MiniMax API key configured. Set MINIMAX_API_KEY or MINIMAX_CN_API_KEY."})

    elif provider == "minimax":
        api_key = _get_minimax_api_key()
        if not api_key:
            return json.dumps({"error": "MINIMAX_API_KEY not configured"})
        result = _check_and_fetch(api_key, MINIMAX_QUOTA_URL, "MiniMax (Global)")
        return result or json.dumps({"error": "Failed to fetch MiniMax quota"})

    elif provider == "minimax-cn":
        api_key = _get_minimax_cn_api_key()
        if not api_key:
            return json.dumps({"error": "MINIMAX_CN_API_KEY not configured"})
        result = _check_and_fetch(api_key, MINIMAX_CN_QUOTA_URL, "MiniMax (China)")
        return result or json.dumps({"error": "Failed to fetch MiniMax CN quota"})

    return json.dumps({"error": f"Unknown provider: {provider}. Use 'minimax', 'minimax-cn', or 'auto'."})


# OpenAI Function-Calling Schema
MINIMAX_QUOTA_SCHEMA = {
    "name": "minimax_quota",
    "description": (
        "Fetch current MiniMax API quota usage and limits. "
        "Shows total credits, used credits, and remaining credits "
        "for the current billing period. Use this to check if you "
        "have enough quota before making API requests."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "provider": {
                "type": "string",
                "enum": ["auto", "minimax", "minimax-cn"],
                "default": "auto",
                "description": (
                    "Which MiniMax provider to check: "
                    "'auto' (default) tries global then China, "
                    "'minimax' for international, "
                    "'minimax-cn' for China endpoint."
                ),
            },
        },
    },
}


# Registry
from tools.registry import registry

registry.register(
    name="minimax_quota",
    toolset="minimax",
    schema=MINIMAX_QUOTA_SCHEMA,
    handler=lambda args, **kw: minimax_quota_tool(provider=args.get("provider", "auto")),
    check_fn=check_minimax_quota_requirements,
    requires_env=["MINIMAX_API_KEY"],
    emoji="📊",
)
