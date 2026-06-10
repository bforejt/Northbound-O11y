"""Minimal PAN-OS XML API client (op commands only)."""
import os
from dataclasses import dataclass

import requests
import xmltodict

GP_USERS_CMD = "<show><global-protect-gateway><current-user/></global-protect-gateway></show>"


@dataclass
class Metric:
    name: str
    labels: dict[str, str]
    value: float


class PanosApiError(Exception):
    pass


def _verify() -> bool | str:
    """PANOS_VERIFY_TLS: true | false | path to a CA bundle."""
    val = os.environ.get("PANOS_VERIFY_TLS", "true").strip()
    if val.lower() in ("true", "1", "yes", ""):
        return True
    if val.lower() in ("false", "0", "no"):
        return False
    return val


def api_key_for(device_name: str) -> str:
    env = "PANOS_API_KEY__" + device_name.upper().replace("-", "_")
    key = os.environ.get(env) or os.environ.get("PANOS_API_KEY")
    if not key:
        raise PanosApiError(f"no API key configured (set {env} or PANOS_API_KEY)")
    return key


def _op_request(device: dict, cmd: str) -> requests.Response:
    # Key goes in the X-PAN-KEY header, not the URL, so it never hits access logs.
    resp = requests.get(
        f"https://{device['host']}/api/",
        params={"type": "op", "cmd": cmd},
        headers={"X-PAN-KEY": api_key_for(device["name"])},
        verify=_verify(),
        timeout=10,
    )
    if resp.status_code == 403:
        raise PanosApiError("HTTP 403: API key invalid or expired -- regenerate it")
    resp.raise_for_status()
    return resp


def op_raw(device: dict, cmd: str) -> str:
    """Raw XML response text, for --dump-raw."""
    return _op_request(device, cmd).text


def op(device: dict, cmd: str) -> dict | None:
    """Run an op command and return the parsed <result> subtree (None if empty)."""
    text = _op_request(device, cmd).text
    response = xmltodict.parse(text).get("response") or {}
    # PAN-OS reports op failures as HTTP 200 with status="error".
    if response.get("@status") != "success":
        raise PanosApiError(f"PAN-OS error response: {text[:300]}")
    return response.get("result")
