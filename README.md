# Web-Based Network Device Monitoring and Fault Detection System

A web-based administrator platform for registering network devices, performing ICMP monitoring, collecting selected SNMP metrics, detecting predefined faults, recording monitoring history, and presenting network health through a React dashboard.

> **Release status:** Final academic-project release preparation (Phase 28). The implementation is documented according to the actual repository behavior and the requirements traced in `docs/PHASE_27_REQUIREMENTS_TRACEABILITY.md`.

## Project Overview

The system centralizes network-device management and monitoring in a web application. An administrator can register devices, configure monitoring, inspect current health, review monitoring/fault history, receive in-application fault notifications, and acknowledge or resolve detected faults.

The backend performs the monitoring and fault-detection work. The frontend consumes the Django REST API and does not duplicate monitoring business logic.

## Scope

Implemented:

- Administrator authentication and protected API access
- Centralized device registration and management
- IPv4 device validation
- Monitoring configuration
- Immediate and periodic ICMP monitoring
- Latency and packet-loss recording
- SNMP v1/v2c metric collection where configured
- HTTP endpoint monitoring (status code and response time) where configured
- Deterministic fault detection and severity assignment
- Fault lifecycle: active, acknowledged, resolved
- In-application notifications
- Monitoring and fault history
- Dashboard health summaries
- Celery/Redis background monitoring infrastructure
- Production deployment configuration for Linux/Nginx/Gunicorn/SQLite/Redis

The project does **not** claim physical interoperability across every network vendor/model, automatic device reconfiguration, intrusion detection, ISP infrastructure monitoring, advanced predictive maintenance, full ML-based network prediction, or hardware-level physical diagnosis. SNMP validation is explicitly controlled/simulated in the academic validation suite.

## Architecture

```text
                         Browser
                            │
                    React / TypeScript
                            │
                         /api
                            │
                          Nginx
                            │
                  Gunicorn → Django WSGI
                            │
              Django REST Framework / API
                            │
       ┌────────────────────┼────────────────────┐
       │                    │                    │
    Devices             Monitoring             Faults
       │                    │                    │
       │             ICMP / HTTP / SNMP    Detection rules
       │                    │                    │
       └────────────────────┼────────────────────┘
                            │
                         SQLite
                            │
                     Celery worker
                            │
                          Redis
                            ▲
                      Celery Beat
```

The backend is WSGI-based (`backend.wsgi:application`). Gunicorn is therefore used for deployment; an ASGI server is not required by the current implementation.

Detailed diagrams and model relationships are in:

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/DATABASE.md`](docs/DATABASE.md)
- [`docs/DFD_UML.md`](docs/DFD_UML.md)

## Technology Stack

| Layer | Technology |
|---|---|
| Frontend | React, TypeScript, Vite, Tailwind CSS v4, Recharts |
| API | Django REST Framework |
| Backend | Python, Django |
| Monitoring | ICMP/Ping, HTTP endpoint probes, PySNMP |
| Background jobs | Celery, Celery Beat |
| Broker/backend | Redis |
| Database | SQLite |
| Production web server | Nginx |
| Application server | Gunicorn / Django WSGI |
| Source control | Git / GitHub |

## Repository Structure

```text
.
├── backend/                 # Django project and network application
├── frontend/                # React/Vite application
├── deploy/                  # Nginx and systemd deployment examples
├── docs/                    # API, architecture, database, validation and academic docs
└── README.md
```

## Requirements

Development requires:

- Python 3.12-compatible environment
- Node.js/npm
- Redis
- Git

Production additionally requires Linux, Nginx, Gunicorn, Redis, and a configured HTTPS certificate before public traffic is enabled.

## Backend Setup

```bash
cd backend
python3 -m venv env
source env/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set a real `DJANGO_SECRET_KEY` in the environment. Do not commit `.env` or production secrets.

Initialize the database:

```bash
python manage.py migrate --noinput
python manage.py createsuperuser
python manage.py runserver
```

Django API: `http://127.0.0.1:8000/`

Public health endpoint:

```text
GET /api/health/
```

## Redis and Celery

Start Redis locally:

```bash
redis-server
```

From `backend/` with the virtual environment active:

```bash
celery -A backend worker -l info
celery -A backend beat -l info
```

Celery Beat dispatches due monitoring work every five seconds. The configured device interval determines whether a device is due for another check. Redis locks prevent overlapping monitoring runs for the same device.

## Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

The Vite development server proxies `/api` to `http://127.0.0.1:8000`.

For another API origin, set:

```env
VITE_API_BASE_URL=/api
```

Do not put secrets in Vite environment variables because `VITE_*` values are bundled into browser code.

## Monitoring Configuration

Every registered device automatically receives a `MonitoringConfiguration`.

Configuration includes:

- monitoring enabled/disabled
- interval in seconds
- SNMP enabled/disabled
- SNMP version
- SNMP community (stored server-side and not exposed by the configuration API)
- SNMP port
- SNMP timeout
- selected metrics
- HTTP endpoint monitoring enabled/disabled
- HTTP endpoint URL (`http://` or `https://`, no embedded credentials)
- HTTP request timeout
- optional exact expected HTTP status (any 2xx/3xx when unset)

The current device model accepts IPv4 addresses only.

## Fault Detection

The implemented deterministic rules cover:

- device unreachable
- high latency
- high packet loss
- high CPU usage from supported SNMP metrics
- high memory usage from supported SNMP metrics
- HTTP endpoint failure (connection failure, or an unexpected status code)
- HTTP slow response

The model also contains interface/connectivity fault types used by the domain model, but they are not represented as a claim of an independent automatic detection algorithm unless supported by the current monitoring path.

Faults have `critical`, `high`, `medium`, or `low` severity and follow:

```text
active → acknowledged → resolved
active → resolved
```

## LLM Fault Explainer

The optional fault explainer turns a detected fault into a structured `Explanation`, `Likely causes`, and `Recommended actions` using a locally fine-tuned Qwen2.5-1.5B LoRA adapter, with a deterministic fallback when the model is disabled or unavailable. It is exposed as `POST /api/faults/<id>/explain/` and surfaced as **Explain this fault** in the fault detail view.

See [`docs/LLM_FINE_TUNING.md`](docs/LLM_FINE_TUNING.md) for dataset design, training configuration, evaluation, integration, limitations, and reproduction steps.

## API Documentation

Start with [`docs/API.md`](docs/API.md) for device and monitoring endpoints.

Additional API references:

- [`docs/FAULT_API.md`](docs/FAULT_API.md)
- [`docs/HISTORICAL_API.md`](docs/HISTORICAL_API.md)
- [`docs/NOTIFICATIONS.md`](docs/NOTIFICATIONS.md)
- [`docs/AUTOMATED_MONITORING.md`](docs/AUTOMATED_MONITORING.md)

Authentication uses Django REST Framework token authentication:

```http
Authorization: Token <token>
```

Protected application endpoints require an authenticated staff administrator.

## Testing and Validation

Backend:

```bash
cd backend
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

Controlled network-monitoring validation:

```bash
python manage.py test network.test_monitoring_validation -v 2
```

Frontend:

```bash
cd frontend
npm run lint
npm run build
```

Deployment configuration validation:

```bash
cd backend
python manage.py check --deploy
```

`check --deploy` requires production environment values such as `DJANGO_SECRET_KEY`, allowed hosts, and HTTPS settings to be supplied. Local HTTP development may intentionally report HTTPS/HSTS warnings when those production values are disabled.

The final academic traceability matrix is in [`docs/PHASE_27_REQUIREMENTS_TRACEABILITY.md`](docs/PHASE_27_REQUIREMENTS_TRACEABILITY.md).

## Deployment

The documented deployment target is a Linux single-origin installation:

```text
Nginx
 ├── React static files
 ├── Django static/media files
 └── /api/ and /admin/
          │
       Gunicorn
          │
      Django WSGI
          │
   SQLite + Celery
          │
        Redis
```

See [`deploy/README.md`](deploy/README.md) for the complete deployment procedure, systemd units, Nginx configuration, environment configuration, HTTPS requirements, backup requirements, and smoke tests.

SQLite is the current documented deployment database for this project. PostgreSQL is not part of the finalized deployment contract.

## Screenshots and Demonstration

The repository does not embed generated UI screenshots because screenshots depend on the deployed/demo environment and are not required by the runtime implementation. For an academic demonstration, capture the running application showing:

1. Administrator login
2. Dashboard
3. Device registration/configuration
4. Device monitoring details
5. Active fault
6. Fault acknowledgement/resolution
7. Monitoring history
8. Fault history
9. Notifications

These screenshots should be taken from the final validated build rather than represented as static implementation claims in source documentation.

## Academic Documentation

- [`docs/Chapter One- Network Device Monitoring and Fault Detection.docx`](docs/Chapter%20One-%20Network%20Device%20Monitoring%20and%20Fault%20Detection.docx)
- [`docs/Chapter Three – System Analysis and Methodology.docx`](docs/Chapter%20Three%20%E2%80%93%20System%20Analysis%20and%20Methodology.docx)
- [`docs/PHASE_27_REQUIREMENTS_TRACEABILITY.md`](docs/PHASE_27_REQUIREMENTS_TRACEABILITY.md)

## Release Documentation

- [`docs/PHASE_28_FINAL_RELEASE.md`](docs/PHASE_28_FINAL_RELEASE.md)
- [`RELEASE_NOTES.md`](RELEASE_NOTES.md)

## Author

**Abdulmumin Abubakar**  
AI Engineer | Software Engineer | Founder, Echowavs
