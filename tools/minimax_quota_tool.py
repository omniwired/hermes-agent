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
    if provider == "auto":
        # Try global first, then China
        api_key = _get_minimax_api_key()
        if api_key:
            try:
                data = _fetch_quota(api_key, MINIMAX_QUOTA_URL)
                return json.dumps({
                    "provider": "minimax",
                    "data": data,
                    "formatted": _format_quota_response(data, "MiniMax (Global)"),
                })
            except Exception as e:
                logger.warning("Failed to fetch MiniMax global quota: %s", e)

        # Fall back to China
        api_key = _get_minimax_cn_api_key()
        if api_key:
            try:
                data = _fetch_quota(api_key, MINIMAX_CN_QUOTA_URL)
                return json.dumps({
                    "provider": "minimax-cn",
                    "data": data,
                    "formatted": _format_quota_response(data, "MiniMax (China)"),
                })
            except Exception as e:
                return json.dumps({"error": f"Failed to fetch MiniMax CN quota: {e}"})

        return json.dumps({"error": "No MiniMax API key configured. Set MINIMAX_API_KEY or MINIMAX_CN_API_KEY."})

    elif provider == "minimax":
        api_key = _get_minimax_api_key()
        if not api_key:
            return json.dumps({"error": "MINIMAX_API_KEY not configured"})
        try:
            data = _fetch_quota(api_key, MINIMAX_QUOTA_URL)
            return json.dumps({
                "provider": "minimax",
                "data": data,
                "formatted": _format_quota_response(data, "MiniMax (Global)"),
            })
        except Exception as e:
            return json.dumps({"error": f"Failed to fetch quota: {e}"})

    elif provider == "minimax-cn":
        api_key = _get_minimax_cn_api_key()
        if not api_key:
            return json.dumps({"error": "MINIMAX_CN_API_KEY not configured"})
        try:
            data = _fetch_quota(api_key, MINIMAX_CN_QUOTA_URL)
            return json.dumps({
                "provider": "minimax-cn",
                "data": data,
                "formatted": _format_quota_response(data, "MiniMax (China)"),
            })
        except Exception as e:
            return json.dumps({"error": f"Failed to fetch quota: {e}"})

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
