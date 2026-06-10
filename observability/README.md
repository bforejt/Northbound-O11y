# Network Observability Platform — Stage 1

Platform core (VictoriaMetrics + Grafana) plus the poll-lane connector with one
module: **GlobalProtect connected-user counts per gateway**, polled from Palo
Alto firewalls over the PAN-OS XML API (HTTPS). Everything is declared in this
repo and deployed with Docker Compose. No SNMP anywhere.

```
firewalls --HTTPS/XML API--> panos-connector --push--> VictoriaMetrics <-- Grafana
```

## Setup

1. Clone the repo and `cd observability/`.
2. Copy the env template and fill it in:

   ```sh
   cp .env.example .env
   ```

   At minimum set `GRAFANA_ADMIN_PASSWORD` and `PANOS_API_KEY`
   (see [Generating an API key](#generating-an-api-key)).
3. Edit `inventory/devices.yaml` to list your firewalls.
4. Start the stack:

   ```sh
   docker compose up -d
   ```

5. Open Grafana at <http://localhost:3000> (user `admin`, the password from
   `.env`). The **GlobalProtect Gateways** dashboard is in the **Network**
   folder. With the default 60 s poll interval you should see data within
   ~2 minutes of startup.

## Generating an API key

Use a dedicated account with the minimum role, not your admin login:

1. On the firewall, create a custom **admin role** with everything disabled
   except **XML API → Operational Requests**.
2. Create a dedicated administrator account bound to that role.
3. Generate the key:

   ```sh
   curl -k 'https://<firewall>/api/?type=keygen&user=<user>&password=<password>'
   ```

4. Put the key in `.env` as `PANOS_API_KEY` (shared) or
   `PANOS_API_KEY__FW_EAST_01=...` (per device: name uppercased, `-` → `_`).

Key lifetime follows the device's *API key lifetime* setting
(Device → Setup → Management → Authentication Settings). **An HTTP 403 in the
connector logs means the key is invalid or expired — regenerate it.**

`PANOS_VERIFY_TLS` controls certificate checking: `true`, `false`, or a path
to a CA bundle (mount it into the connector container if you use one).

## First-run verification

GlobalProtect XML element names vary across PAN-OS versions, so verify them
against a real firewall before trusting the numbers.

**1. Dump the raw XML for one device:**

```sh
docker compose run --rm --no-deps panos-connector --dump-raw fw-east-01
```

Check that each `<entry>` carries a gateway-name field and a username field.
The connector looks for `gateway`/`gateway-name` and
`username`/`primary-username` — if your version uses different names, extend
the candidate lists at the top of `connector/modules/gp_gateway.py`.

> **Note:** publicly documented PAN-OS versions (8.x–11.x) do *not* include a
> gateway-name element in each `<entry>` for this command. If yours doesn't
> either, all of a device's users are counted under `gateway="unknown"` —
> per-device totals stay correct. Confirm what your version emits with
> `--dump-raw` before trusting the per-gateway split.

**2. Run one poll cycle without a TSDB:**

```sh
docker compose run --rm --no-deps panos-connector --once
```

This prints the metrics in Prometheus text format to stdout and does not POST
anywhere. Expected shape:

```
# TYPE panos_connector_up gauge
panos_connector_up{device="fw-east-01"} 1
# TYPE panos_gp_current_users gauge
panos_gp_current_users{device="fw-east-01",gateway="gw-east",site="east"} 42
...
```

If parsing fails, set `LOG_LEVEL=DEBUG` in `.env` to log the raw structures.

## Adding a device

1. Add an entry to `inventory/devices.yaml`:

   ```yaml
   - name: fw-south-01
     host: 10.0.30.1
     site: south
     role: gp-gateway
   ```

2. Optionally add a per-device key in `.env`: `PANOS_API_KEY__FW_SOUTH_01=...`
   (falls back to `PANOS_API_KEY`).
3. `docker compose restart panos-connector`.

A device that stops answering only affects itself: its `panos_connector_up`
goes to 0 (and the provisioned alert fires after 5 minutes); all other devices
keep reporting.

## Metrics

| Metric | Labels | Meaning |
| --- | --- | --- |
| `panos_gp_current_users` | `device,gateway,site` | Connected GP sessions per gateway |
| `panos_gp_unique_users` | `device,gateway,site` | Distinct usernames per gateway |
| `panos_connector_up` | `device` | 1 = last poll succeeded, 0 = failed |
| `panos_connector_scrape_duration_seconds` | `device` | Wall time of the last poll |

Per-user data (usernames, IPs, hostnames) is **never** emitted as labels —
counting happens in the connector. Keep it that way in future modules.

## Adding a future module

The seam is one function signature. Create
`connector/modules/<name>.py` exposing:

```python
def collect(api, device: dict) -> list[Metric]: ...
```

`api` is the `panos_api` module (use `api.op(device, cmd)`), `device` is the
inventory entry. Append the function to the `MODULES` list in
`connector/main.py`. No registry, no entry points — that is deliberate.

## Future stages (not built here)

Streaming lane (gnmic/gNMI for IOS-XE, NX-OS, PAN-OS OpenConfig), NetBox as
source of truth rendering `inventory/devices.yaml`, VictoriaLogs for syslog.
The inventory file shape is the NetBox contract — don't extend it casually.
