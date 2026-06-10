"""GlobalProtect gateway connected-user counts.

Module seam: collect(api, device) -> list[Metric]. `api` is the panos_api
module; future modules follow the same signature.
"""
import logging

from panos_api import GP_USERS_CMD, Metric, PanosApiError

log = logging.getLogger(__name__)

# Element names vary across PAN-OS versions; verify with --dump-raw on first
# run against a real firewall and extend these candidate lists if needed.
GATEWAY_KEYS = ("gateway", "gateway-name")
# username first: it is present in every version and consistent across one
# user's sessions, while primary-username can be empty on some entries --
# mixing the two would double-count a user.
USERNAME_KEYS = ("username", "primary-username")


def _as_list(value) -> list:
    """xmltodict yields a dict for one <entry> and a list for many."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _first(entry: dict, keys: tuple) -> str | None:
    for key in keys:
        if entry.get(key):
            return str(entry[key])
    return None


def collect(api, device: dict) -> list[Metric]:
    result = api.op(device, GP_USERS_CMD)
    if result is not None and not isinstance(result, dict):
        log.debug("%s: unexpected result shape: %r", device["name"], result)
        raise PanosApiError("unexpected <result> structure (run --dump-raw)")
    entries = _as_list((result or {}).get("entry"))
    if result and not entries:
        log.debug("%s: no <entry> elements found, raw result: %r", device["name"], result)

    gateways: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            log.debug("%s: skipping malformed entry: %r", device["name"], entry)
            continue
        gw = _first(entry, GATEWAY_KEYS)
        if gw is None:
            log.debug("%s: entry has no gateway field, raw entry: %r", device["name"], entry)
            gw = "unknown"
        agg = gateways.setdefault(gw, {"total": 0, "users": set()})
        agg["total"] += 1
        user = _first(entry, USERNAME_KEYS)
        if user:
            agg["users"].add(user)  # counted here, never emitted as a label

    metrics = []
    for gw, agg in sorted(gateways.items()):
        labels = {"device": device["name"], "gateway": gw, "site": device.get("site", "")}
        metrics.append(Metric("panos_gp_current_users", labels, agg["total"]))
        metrics.append(Metric("panos_gp_unique_users", labels, len(agg["users"])))
    return metrics
