# DOGFOOD 2026 Hackathon Platform

Production-grade, offline-first hackathon management platform engineered with Django 5.x, Python 3.11+, and PostgreSQL 16.

---

## 1. Team Responsibilities & Ownership Split

The project was executed by a two-person team with clear architectural division of responsibility:

| Area / Component | Primary Owner | Status |
| :--- | :---: | :---: |
| **T1: Core Foundation & Public Gallery** | Person A | **Shipped & Merged** |
| **T2: Judging Engine & Peer Isolation** | Person B | **Shipped & Merged** |
| **T3: Voting Backend (Atomic models, seeded ordering, results hiding, rate limiting, audit)** | Person A | **Shipped & Merged** |
| **T3: Voting Frontend (Ballot UI, pre/post-close Results UI, Comments UI)** | Person A | **Shipped & Merged** |
| **T4: Certificates (Issuance & Public Retrieval)** | Person A | **Shipped & Merged** |
| **T4: Signed Judge Participation Records (Ed25519 & Offline Verifier)** | Person A | **Shipped & Merged** |
| **T4: Embeddable Public Gallery Widget (iframe + JS helper + framing headers)** | Person A | **Shipped & Merged** |
| **T4: Bulk Data Operations (Sanitized JSON export & atomic pre-validated import)** | Person B | **Shipped & Merged** |
| **T4: OpenAPI 3.0.3 Schema Endpoint** | Person B | **Shipped & Merged** |
| **Webhooks** | Both | **CUT / DEFERRED** (Deprioritized per team plan) |

---

## 2. Tech Stack & Infrastructure

- **Backend:** Python 3.11+ / Django 5.x / Django REST Framework (DRF)
- **Database:** PostgreSQL 16 (`psycopg2-binary`) with MVCC, transactional consistency, and row-level locking
- **Containerization:** Docker & Docker Compose (`db` and `web` services)
- **Authentication:** Django standard session authentication (`SESSION_COOKIE_NAME = "session"`)
- **Frontend:** Server-rendered Django templates + locally vendored Bootstrap 5 + minimal vanilla JS (zero external build tools or node dependencies)
- **Static Assets:** WhiteNoise (`CompressedManifestStaticFilesStorage`) guaranteeing complete offline functionality
- **Cryptography:** Ed25519 digital signatures (`cryptography>=44.0.0`) with RFC 8785 canonical JSON formatting

---

## 3. Quickstart with Docker Compose

1. **Start the environment (from a clean volume):**
   ```bash
   docker compose down -v
   docker compose up --build -d
   ```

2. **Automated Startup Sequence (`entrypoint.sh`):**
   The `web` container waits for PostgreSQL health check (`pg_isready -U dogfood`), then executes:
   - Dynamic `SECRET_KEY` generation if not supplied in environment
   - `python manage.py collectstatic --noinput`
   - `python manage.py migrate --noinput`
   - `python manage.py seed_fixtures` (loads `fixtures.json` idempotently)
   - `python manage.py create_checker_sessions` (pre-seeds test sessions for checker accounts)
   - `python manage.py runserver 0.0.0.0:8080`

3. **Accessing the Application:**
   - **Public Gallery:** [http://localhost:8080/projects](http://localhost:8080/projects)
   - **Voting Ballot (Authenticated):** [http://localhost:8080/vote/1/](http://localhost:8080/vote/1/)
   - **Voting Ballot (Link/Token):** [http://localhost:8080/vote/link/<token>/](http://localhost:8080/vote/link/<token>/)
   - **Results Page (Hidden pre-close / Real post-close):** [http://localhost:8080/results/1/](http://localhost:8080/results/1/)
   - **Embeddable Gallery Widget:** [http://localhost:8080/embed/gallery/1/](http://localhost:8080/embed/gallery/1/)
   - **Widget JS Helper:** [http://localhost:8080/embed/gallery.js](http://localhost:8080/embed/gallery.js)
   - **Judging Scores API:** [http://localhost:8080/api/judge/scores/](http://localhost:8080/api/judge/scores/)
   - **CSV Export:** [http://localhost:8080/api/export.csv](http://localhost:8080/api/export.csv)
   - **Bulk Export:** [http://localhost:8080/api/export/bulk/](http://localhost:8080/api/export/bulk/)
   - **Bulk Import:** [http://localhost:8080/api/import/bulk/](http://localhost:8080/api/import/bulk/)
   - **OpenAPI Schema:** [http://localhost:8080/api/schema/](http://localhost:8080/api/schema/)
   - **Ed25519 Public Key:** [http://localhost:8080/api/t4/keys/public/](http://localhost:8080/api/t4/keys/public/)
   - **Public Record Verification:** [http://localhost:8080/api/verify/<record_id>/](http://localhost:8080/api/verify/<record_id>/)

---

## 4. Verification & Testing

### 4.1 Official Acceptance Checker (`run.py`)
Run the official checker against the active service on port 8080:
```bash
python run.py .dogfood.toml
```

**Verification Boundary Clarification:**
- The official `run.py` script tests **only Tier 1 (T1) and Tier 2 (T2)**.
- `claimed = ["T1", "T2"]` in `.dogfood.toml` matches the official checker scope with 100% pass rate:
  ```text
  T1  gallery is public ................. PASS
  T1  project from fixtures shown ....... PASS
  T1  closed event refuses submissions .. PASS
  T2  judge sees own scores ............. PASS
  T2  judge cannot see peer scores ...... PASS
  T2  participant blocked ............... PASS
  T2  csv export works .................. PASS

  claimed T1 T2, verified T1 T2
  ```
- **T3 and T4 are separately self-verified** via automated unit/integration tests and manual verification scripts. We do NOT falsely claim or modify `run.py` to verify T3/T4.

### 4.2 Comprehensive Django Test Suite
The full test suite covers all installed apps:
```bash
docker compose exec web python manage.py test accounts core events teams projects voting audit t4
```
**Current Test Results:**
- **224 tests passed** across all apps with **0 failures and 0 errors**.
- Breakdown:
  - `accounts`, `core`, `events`, `teams`, `projects`: T1 core and gallery tests
  - `judging`: T2 role isolation and score handling
  - `voting`: T3 backend voting, token mechanics, rate limiting, and 9 frontend UI tests
  - `audit`: T3 immutable audit trail logging
  - `t4`: T4 certificates, Ed25519 signing, verification CLI, bulk import/export, OpenAPI schema, and 8 widget tests

### 4.3 Offline Cryptographic Verification CLI
Verify signed judge records offline without network access:
```bash
docker compose exec web python manage.py verify_judge_record <record_id>
```

---

## 5. Shipped Functionality Overview

### 5.1 Tier 1: Core Portal & Public Gallery
- Responsive project gallery (`/projects`) with text search (`?q=`) and track filtering (`?track=`).
- Project detail page (`/projects/<id>/`) with status badge, team info, and submission metadata.
- Project creation and edit forms strictly enforcing `submissions_close` deadline.
- Idempotent data loader (`manage.py seed_fixtures`) reading from `fixtures.json`.

### 5.2 Tier 2: Judging Engine & Role Isolation
- Rubric-based score capture via `POST /api/judge/scores/`.
- Strict RBAC: unauthenticated users (401), participants/visitors (403), judges restricted to assigned projects.
- Peer score isolation: judges cannot inspect other judges' scores (`GET /api/judge/scores/?judge=<peer>` returns 403).
- Read-time Z-score dynamic normalization with zero-variance protection ($\sigma < 10^{-4} \implies \sigma = 1.0$).
- RFC 4180 CSV export endpoint (`/api/export.csv`) restricted to organizers and admins.

### 5.3 Tier 3: Community Voting, Results & Comments
- **Backend:**
  - Authenticated voting (`POST /api/vote/`) and link-based single-use token voting (`POST /api/vote/link/<token>/`).
  - Database-enforced constraints preventing duplicate votes (`unique_vote_per_user`, `unique_vote_per_token_total`).
  - Deterministic SHA-256 seeded ballot ordering per voter identity, eliminating position bias.
  - Active-window results hiding: `GET /api/results/<event_id>/` returns HTTP 403 with `results_hidden: true` until `voting_close`.
  - In-memory cache rate limiting on vote endpoints.
  - Immutable audit trail logging (`AuditEvent`) recording all vote attempts, rejections, and anomalies.
- **Frontend:**
  - Complete voting ballot UI (`/vote/<event_id>/` and `/vote/link/<token>/`) with backend-seeded order, status badges, and AJAX/form error handling.
  - Results page (`/results/<event_id>/`) strictly concealing tallies pre-close, displaying full sorted leaderboard post-close.
  - Comments UI on project detail page (`/projects/<id>/`) with live listing and AJAX submission to `/api/projects/<id>/comments/`.

### 5.4 Tier 4: Attestations, Widget & Bulk Operations
- **Certificates:** Model, REST API (`/api/t4/certificates/`), and public view for issuing verifiable hackathon awards.
- **Signed Judge Records:** Real Ed25519 digital signatures on RFC 8785 canonical JSON payloads.
  - Key management: 32-byte private seed kept in `/keys/t4_signing_key` with strict permissions.
  - Public key distribution: `GET /api/t4/keys/public/`.
  - REST verification: `GET /api/verify/<record_id>/`.
  - Offline verification: `manage.py verify_judge_record <id>` command.
- **Embeddable Gallery Widget:**
  - Public embed route: `GET /embed/gallery/<event_id>/` (supports integer ID or string `external_id`).
  - Drop-in JS helper: `GET /embed/gallery.js`.
  - Public-safe data isolation: exposes only public showcase fields, strictly omitting scores, invite codes, tokens, passwords, and private keys.
  - Framing security: `@xframe_options_exempt` and CSP `frame-ancestors *` relax framing *only* on the embed route; all other routes retain `X-Frame-Options: DENY`.
- **Bulk Import & Export (Person B):**
  - Sanitized bulk JSON export (`/api/export/bulk/`) scrubbing all credentials and tokens.
  - Atomic bulk JSON import (`/api/import/bulk/`) with whole-payload pre-validation, `?dry_run=true` simulation, and `external_id` reconciliation.
- **OpenAPI 3.0.3 Specification (Person B):**
  - Standalone machine-readable schema served at `/api/schema/` and `/api/openapi.json`.

---

## 6. Deferred & Cut Scope

- **Webhooks:** Explicitly cut per the agreed team priority split. Not implemented.
