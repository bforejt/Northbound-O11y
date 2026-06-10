"""PAN-OS poll-lane connector: poll devices, push metrics to VictoriaMetrics."""
import argparse
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests
import yaml

import panos_api
from panos_api import Metric
from modules import gp_gateway

log = logging.getLogger("panos-connector")

# The module seam: each entry is collect(api, device) -> list[Metric].
MODULES = [gp_gateway.collect]


def load_devices(path: str) -> list[dict]:
    with open(path) as fh:
        data = yaml.safe_load(fh) or {}
    devices = data.get("devices") or []
    if not devices:
        log.warning("no devices defined in %s", path)
    return devices


def poll_device(device: dict) -> list[Metric]:
    name = device["name"]
    start = time.monotonic()
    metrics: list[Metric] = []
    up = 1
    for collect in MODULES:
        try:
            metrics.extend(collect(panos_api, device))
        except requests.exceptions.Timeout:
            log.error("%s: timed out after 10s talking to %s", name, device["host"])
            up = 0
        except Exception as exc:
            log.error("%s: poll failed: %s", name, exc)
            up = 0
    metrics.append(Metric("panos_connector_up", {"device": name}, up))
    metrics.append(Metric(
        "panos_connector_scrape_duration_seconds", {"device": name},
        time.monotonic() - start,
    ))
    return metrics


def run_cycle(devices: list[dict]) -> list[Metric]:
    with ThreadPoolExecutor(max_workers=10) as pool:
        return [m for batch in pool.map(poll_device, devices) for m in batch]


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def serialize(metrics: list[Metric]) -> str:
    """Prometheus text exposition format, families grouped, no timestamps."""
    lines, seen = [], set()
    for m in sorted(metrics, key=lambda m: m.name):
        if m.name not in seen:
            seen.add(m.name)
            lines.append(f"# TYPE {m.name} gauge")
        labels = ",".join(f'{k}="{_escape(str(v))}"' for k, v in sorted(m.labels.items()))
        lines.append(f"{m.name}{{{labels}}} {m.value:.10g}")
    return "\n".join(lines) + "\n"


def push(vm_url: str, body: str) -> None:
    url = vm_url.rstrip("/") + "/api/v1/import/prometheus"
    resp = requests.post(url, data=body.encode(), timeout=10)
    resp.raise_for_status()


def main() -> int:
    parser = argparse.ArgumentParser(description="PAN-OS poll-lane connector")
    parser.add_argument("--config", default="/config/devices.yaml")
    parser.add_argument("--interval", type=int,
                        default=int(os.environ.get("POLL_INTERVAL", "60")))
    parser.add_argument("--once", action="store_true",
                        help="single cycle, print metrics to stdout, no POST")
    parser.add_argument("--dump-raw", metavar="DEVICE_NAME",
                        help="print one device's raw XML response and exit")
    args = parser.parse_args()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    devices = load_devices(args.config)
    if args.dump_raw:
        device = next((d for d in devices if d["name"] == args.dump_raw), None)
        if device is None:
            log.error("device %r not in %s", args.dump_raw, args.config)
            return 1
        print(panos_api.op_raw(device, panos_api.GP_USERS_CMD))
        return 0
    if args.once:
        sys.stdout.write(serialize(run_cycle(devices)))
        return 0

    vm_url = os.environ.get("VM_URL", "http://victoriametrics:8428")
    log.info("polling %d device(s) every %ds, pushing to %s", len(devices), args.interval, vm_url)
    while True:
        start = time.monotonic()
        metrics = run_cycle(devices)
        try:
            push(vm_url, serialize(metrics))
        except Exception as exc:
            log.error("push to %s failed: %s", vm_url, exc)
        time.sleep(max(0.0, args.interval - (time.monotonic() - start)))


if __name__ == "__main__":
    sys.exit(main())
