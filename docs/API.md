# Backend API — Device and Monitoring

## Authentication

Protected application endpoints require a Django REST Framework token belonging to an active staff administrator.

```http
Authorization: Token <token>
```

Unauthenticated requests receive `401 Unauthorized`. Authenticated non-staff users receive `403 Forbidden`.

## Authentication endpoints

```http
POST /api/auth/login/
POST /api/auth/logout/
GET  /api/auth/me/
```

The health endpoint is intentionally public:

```http
GET /api/health/
```

## Device resource

| API field | Backend field | Notes |
|---|---|---|
| `id` | `id` | UUID, read-only |
| `name` | `name` | Required, max 120 characters |
| `ipAddress` | `ip_address` | Required IPv4 address |
| `type` | `device_type` | Required device type |
| `status` | `status` | Server-controlled monitoring state |
| `monitoring` | `monitoring_enabled` | Enables/disables monitoring |
| `createdAt` | `created_at` | Read-only |
| `updatedAt` | `updated_at` | Read-only |

Supported device types:

- `router`
- `switch`
- `server`
- `access-point`
- `firewall`
- `other`

Supported status values:

- `online`
- `offline`
- `unknown`

## Device endpoints

```http
GET    /api/devices/
POST   /api/devices/
GET    /api/devices/<id>/
PATCH  /api/devices/<id>/
PUT    /api/devices/<id>/
DELETE /api/devices/<id>/
PATCH  /api/devices/<id>/monitoring/
GET    /api/devices/<id>/monitoring-config/
PATCH  /api/devices/<id>/monitoring-config/
POST   /api/devices/<id>/monitor/
GET    /api/devices/<id>/monitoring-snapshot/
GET    /api/devices/<id>/monitoring-summary/
```

Example registration:

```json
{
  "name": "Core Router",
  "ipAddress": "192.168.1.1",
  "type": "router",
  "monitoring": true
}
```

A successful registration returns `201 Created` and automatically creates the device's one-to-one `MonitoringConfiguration` with defaults.

Device deletion is destructive and cascades to related monitoring configuration, monitoring records, SNMP metrics, and faults.

## MonitoringRecord

Each monitoring execution creates a new immutable historical `MonitoringRecord`.

| Field | Description |
|---|---|
| `id` | UUID |
| `deviceId` | Device UUID |
| `timestamp` | Measurement timestamp |
| `reachable` | ICMP reachability |
| `latencyMs` | Response latency, when available |
| `packetLossPercent` | Packet-loss result, when available |
| `httpOk` | HTTP probe result, or `null` when no endpoint is configured |
| `httpStatusCode` | HTTP status code, or `null` if the request never completed |
| `httpResponseTimeMs` | HTTP response time, when measured |
| `httpError` | HTTP failure reason, empty on success |

## ICMP monitoring

```http
POST /api/devices/<id>/monitor/
```

The endpoint executes one bounded IPv4 ICMP check, stores a `MonitoringRecord`, updates device status, evaluates relevant fault rules, and returns the stored result.

The implementation validates IPv4 addresses and invokes the system ping utility without a shell. Timeout, missing utility, and network failures are converted into monitoring failure results rather than unhandled API exceptions.

Example successful response:

```json
{
  "id": "<record-uuid>",
  "deviceId": "<device-uuid>",
  "timestamp": "2026-09-15T06:30:00Z",
  "reachable": true,
  "latencyMs": 4.32,
  "packetLossPercent": 0.0,
  "httpOk": null,
  "httpStatusCode": null,
  "httpResponseTimeMs": null,
  "httpError": ""
}
```

`httpOk` is `null` here because no HTTP endpoint is configured for the device.

## Monitoring snapshot

```http
GET /api/devices/<id>/monitoring-snapshot/
GET /api/devices/<id>/monitoring-snapshot/?history=<1-500>
```

Returns the device, latest record, up to `history` records (default 50, capped at 500), SNMP
metrics, and the monitoring configuration. The history array feeds the device detail trend charts;
records are returned newest first.

## Monitoring records

```http
GET /api/monitoring-records/
GET /api/monitoring-records/?deviceId=<device-uuid>
```

Records are returned newest first.

## Monitoring history

```http
GET /api/monitoring-history/
GET /api/monitoring-history/?deviceId=<device-uuid>
GET /api/monitoring-history/?from=<iso-datetime>&to=<iso-datetime>
```

Supported filters include device, date/time range, reachability, and bounded `limit`. Minute/hour/day aggregation is available through the historical API where applicable.

See [`HISTORICAL_API.md`](HISTORICAL_API.md).

## Monitoring configuration

A device has one `MonitoringConfiguration` containing:

- interval seconds
- SNMP enablement
- SNMP version
- SNMP community
- SNMP port
- SNMP timeout
- selected metrics
- HTTP endpoint monitoring enablement
- HTTP endpoint URL
- HTTP request timeout
- optional exact expected HTTP status

The SNMP community is stored server-side and is not returned by the configuration API.

HTTP monitoring settings are read and written through the existing monitoring configuration endpoint:

```http
GET   /api/devices/<id>/monitoring-config/
PATCH /api/devices/<id>/monitoring-config/
```

```json
{
  "httpMonitoringEnabled": true,
  "httpUrl": "https://example.com/health",
  "httpTimeoutSeconds": 3.0,
  "httpExpectedStatus": null
}
```

Enabling HTTP monitoring without a URL, or supplying a non-`http(s)` URL, returns `400`.
`httpExpectedStatus` accepts `100`–`599`; leave it unset to accept any `2xx`/`3xx` response.

## HTTP endpoint monitoring

When an endpoint is configured, every monitoring run probes it alongside ICMP and records the
result on the same `MonitoringRecord`:

- `httpOk` — whether the endpoint returned an acceptable response
- `httpStatusCode` — the status code, or `null` if the request never completed
- `httpResponseTimeMs` — measured response time
- `httpError` — the failure reason, empty on success

These fields stay `null` when no endpoint is configured, which distinguishes "not probed" from
"probed and failed". ICMP and HTTP are evaluated independently: a host can be unreachable by ping
while its endpoint is healthy, and vice versa.

Probe failures raise `HTTP_ENDPOINT_FAILURE`; a healthy but slow endpoint raises
`HTTP_SLOW_RESPONSE`. Both follow the normal active → acknowledged → resolved lifecycle.

## SNMP

The backend supports configured SNMPv1/v2c collection through PySNMP. Current implemented metrics include `sysDescr`, `sysName`, `sysUpTime`, and `ifNumber`.

SNMP failures are isolated from ICMP monitoring. Academic validation uses controlled/simulated SNMP results and therefore does not claim universal physical-device interoperability.

## Faults and notifications

Faults are generated by the monitoring/fault-detection services rather than arbitrary client creation. See:

- [`FAULT_API.md`](FAULT_API.md)
- [`NOTIFICATIONS.md`](NOTIFICATIONS.md)

## Validation behavior

Invalid IPv4 addresses, unsupported device types, invalid monitoring configuration, and disabled-monitoring requests return validation errors without creating an invalid monitoring record.

Monitoring configuration intervals have a minimum supported value of five seconds.
