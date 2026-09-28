# dogfood-2026

DOGFOOD 2026 Hackathon Platform — Project Scaffold & Foundation.

## Tech Stack
- **Backend:** Python 3.11+ / Django / Django REST Framework
- **Database:** PostgreSQL 16 (`psycopg2-binary`)
- **Containerization:** Docker & Docker Compose (`db` and `web` services)
- **Authentication:** Django session authentication (`SESSION_COOKIE_NAME = "session"`)
- **Static Assets:** WhiteNoise (`CompressedManifestStaticFilesStorage`) serving locally vendored Bootstrap
- **Frontend (planned):** Server-rendered Django templates + vendored Bootstrap

## Project Structure
- `config/`: Django project settings, WSGI/ASGI, WhiteNoise storage, and root URL routing
- `core/`: Base management commands including `seed_fixtures` scaffold
- `accounts/`: User authentication and `Profile` model (roles: visitor, participant, judge, organizer, admin)
- `events/`: Hackathon `Event` and `Track` models
- `teams/`: Team formation (`Team`, `TeamMembership`) with invite code support
- `projects/`: Submission models (`Project`) linked to team and track with same-event validation
- `static/`: Locally vendored assets (`static/css/bootstrap.min.css`)
- `Dockerfile` & `docker-compose.yml`: Reproducible containerized deployment with Postgres 16 health check
- `entrypoint.sh`: Orchestrated container startup sequence with automatic `SECRET_KEY` generation and `collectstatic`

## Quickstart with Docker Compose

Ensure Docker and Docker Compose are installed and running.

1. **Start the environment (from a clean volume):**
   ```bash
   docker compose down -v
   docker compose up --build -d
   ```

2. **Automated Startup Sequence:**
   The `web` service waits for `db` to pass its health check (`pg_isready -U dogfood`), then automatically executes:
   - Dynamic `SECRET_KEY` generation via `get_random_secret_key()` if not provided in environment
   - `python manage.py collectstatic --noinput`
   - `python manage.py migrate --noinput`
   - `python manage.py seed_fixtures`
   - `python manage.py runserver 0.0.0.0:8080`

3. **Access the application:**
   Open [http://localhost:8080](http://localhost:8080) in your browser.
   Static assets (e.g., [http://localhost:8080/static/css/bootstrap.min.css](http://localhost:8080/static/css/bootstrap.min.css)) are served via WhiteNoise with `DEBUG=False`.

## Environment Variables
- `DATABASE_URL`: PostgreSQL connection string (defaults to `postgres://dogfood:dogfood_dev_only@db:5432/dogfood`)
- `SECRET_KEY`: Optional in Docker (automatically generated on startup by `entrypoint.sh`); required if running outside Docker
- `DEBUG`: Defaults to `False` everywhere (production-safe default)
- `ALLOWED_HOSTS`: Comma-separated list of allowed hostnames
