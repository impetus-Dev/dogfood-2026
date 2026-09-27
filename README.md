# dogfood-2026

DOGFOOD 2026 Hackathon Platform — Project Scaffold & Foundation.

## Tech Stack
- **Backend:** Python 3.11+ / Django / Django REST Framework
- **Database:** PostgreSQL 16 (`psycopg2-binary`)
- **Containerization:** Docker & Docker Compose (`db` and `web` services)
- **Authentication:** Django session authentication (`SESSION_COOKIE_NAME = "session"`)
- **Frontend (planned):** Server-rendered Django templates + vendored Bootstrap

## Project Structure
- `config/`: Django project settings, WSGI/ASGI, and root URL routing
- `core/`: Base management commands including `seed_fixtures` scaffold
- `accounts/`: User authentication and `Profile` model (roles: visitor, participant, judge, organizer, admin)
- `events/`: Hackathon `Event` and `Track` models
- `teams/`: Team formation (`Team`, `TeamMembership`) with invite code support
- `projects/`: Submission models (`Project`) linked to team and track
- `Dockerfile` & `docker-compose.yml`: Reproducible containerized deployment with Postgres health check
- `entrypoint.sh`: Orchestrated container startup sequence

## Quickstart with Docker Compose

Ensure Docker and Docker Compose are installed.

1. **Start the environment (from a clean volume):**
   ```bash
   docker compose down -v
   docker compose up --build
   ```

2. **Automated Startup Sequence:**
   The `web` service waits for `db` to pass its health check (`pg_isready -U dogfood`), then runs:
   - `python manage.py migrate`
   - `python manage.py seed_fixtures`
   - `python manage.py runserver 0.0.0.0:8080`

3. **Access the application:**
   Open [http://localhost:8080](http://localhost:8080) in your browser.

## Environment Variables
- `DATABASE_URL`: PostgreSQL connection string (defaults to `postgres://dogfood:dogfood_dev_only@db:5432/dogfood`)
- `SECRET_KEY`: Django cryptographic secret key
- `DEBUG`: Set to `True` for development, `False` for production
- `ALLOWED_HOSTS`: Comma-separated list of allowed hostnames
