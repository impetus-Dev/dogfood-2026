# DOGFOOD 2026 — Master Demo Recording Script & Checklist

This script is a concrete, step-by-step manual recording guide for Person A. It covers all verified functionality shipped in the combined codebase (T1, T2, T3 backend + frontend, T4 certificates, signed records, offline verifier, embeddable widget, bulk import/export, and OpenAPI).

> **Recording Note:** Only mark steps as recorded when manually performed by the presenter. Webhooks are excluded (cut from scope).

---

## Pre-Demo Environment State
- Portal URL: `http://localhost:8080`
- Database: PostgreSQL 16 seeded with `fixtures.json` and checker sessions
- Accounts available:
  - Organizer: `organizer` / session `org_7f2a`
  - Judge A: `judge_a` / session `jdg_a_91bc`
  - Judge B: `judge_b` / session `jdg_b_44de`
  - Participant: `participant` / session `prt_2e88`

---

## Step-by-Step Demo Sequence

### Phase 1: Core Portal & Public Gallery (T1)

#### Step 1: Start Application
- **Command:** `docker compose up --build -d`
- **Action:** Open terminal and run Docker Compose startup.
- **Expected Behavior:** Containers `dogfood-2026-db-1` and `dogfood-2026-web-1` start and pass health check.
- **Success Condition:** `docker compose ps` shows `web` running on port 8080 and `db` healthy.

#### Step 2: Open Public Gallery
- **URL:** `http://localhost:8080/projects`
- **Action:** Navigate in browser as an anonymous visitor.
- **Expected Behavior:** Clean Bootstrap gallery displays submitted hackathon entries loaded from fixtures.
- **Success Condition:** Project cards appear with titles, tracks, and summaries; search input and track dropdown are functional.

#### Step 3: Open Project Detail
- **URL:** `http://localhost:8080/projects/1/`
- **Action:** Click on the first project title link.
- **Expected Behavior:** Project details view opens showing project title, track badge, repository link, team members, and empty or active comments section.
- **Success Condition:** Page loads with status HTTP 200 without requiring login.

---

### Phase 2: Community Voting & Results (T3)

#### Step 4: Login as Voter
- **URL:** `http://localhost:8080/accounts/login/`
- **Action:** Log in using credentials for `participant` (or session cookie `prt_2e88`).
- **Expected Behavior:** Session cookie is set and user is redirected to dashboard or projects gallery with authenticated navigation.
- **Success Condition:** Header shows logged-in status.

#### Step 5: Open Voting Ballot
- **URL:** `http://localhost:8080/vote/1/`
- **Action:** Navigate to the voting ballot for Event 1.
- **Expected Behavior:** Ballot renders with authenticated badge, event info, and project candidates displayed in deterministic backend-seeded order.
- **Success Condition:** Ballot page renders with "Cast Your Vote" buttons for each project.

#### Step 6: Cast a Valid Vote
- **URL:** `http://localhost:8080/vote/1/`
- **Action:** Select a project and submit the vote form.
- **Expected Behavior:** Vote is registered via AJAX / form POST. Success notification displays "Your vote has been recorded!".
- **Success Condition:** Green success banner appears; button indicates voted status.

#### Step 7 & 8: Attempt Duplicate Vote & Show Rejection
- **URL:** `http://localhost:8080/vote/1/`
- **Action:** Attempt to cast a second vote for the same project or another project in the same event.
- **Expected Behavior:** Backend rejects duplicate submission with HTTP 400.
- **Success Condition:** Red alert banner displays: "You have already voted in this event." Duplicate vote is strictly prevented.

#### Step 9 & 10: Open Results Before Close (Results Hidden State)
- **URL:** `http://localhost:8080/results/1/`
- **Action:** Navigate to the results page while event is still in active voting phase (`timezone.now() < voting_close`).
- **Expected Behavior:** Clean "Results Are Hidden" banner informs user that voting is currently active. Zero tallies or project ranks are in the DOM.
- **Success Condition:** Explanatory text displays: "Voting is in progress. Results are hidden until voting officially closes." No scoreboard table is visible.

#### Step 11: Safely Advance Voting Close (Demo Simulation)
- **Command:**
  ```bash
  docker compose exec web python -c "
  from events.models import Event; from django.utils import timezone; from datetime import timedelta
  e = Event.objects.get(pk=1)
  print('ORIGINAL_CLOSE:', e.voting_close)
  e.voting_close = timezone.now() - timedelta(minutes=5)
  e.save()
  print('SIMULATED_CLOSE:', e.voting_close)
  "
  ```
- **Action:** Record original `voting_close` timestamp and temporarily set to 5 minutes in the past.
- **Expected Behavior:** Script outputs original timestamp and confirms simulated close.
- **Success Condition:** Database reflects past close timestamp.

#### Step 12 & 13: Open Results After Close (Real Tallies & Leaderboard)
- **URL:** `http://localhost:8080/results/1/`
- **Action:** Refresh the results page.
- **Expected Behavior:** The closed state triggers real calculation: displays total votes cast, participation stats, and a sorted leaderboard table with real vote counts.
- **Success Condition:** Leaderboard displays projects ranked by actual vote count.

#### Step 13b: Immediately Restore Original Voting Close
- **Command:**
  ```bash
  docker compose exec web python -c "
  from events.models import Event
  from django.utils.dateparse import parse_datetime
  # Restore to original recorded value
  e = Event.objects.get(pk=1)
  # [Set back to original recorded value]
  e.save()
  "
  ```
- **Action:** Restore the event's `voting_close` to its original value immediately after recording.
- **Success Condition:** Original timestamp restored and verified.

---

### Phase 3: Project Comments (T3)

#### Step 14: Open Comments Section
- **URL:** `http://localhost:8080/projects/1/`
- **Action:** Scroll down to the "Community Discussion & Feedback" section.
- **Expected Behavior:** Existing comments list and submission form are visible to logged-in user.
- **Success Condition:** Comment form with textarea and "Post Comment" button renders.

#### Step 15 & 16: Create and Show Persisted Comment
- **URL:** `http://localhost:8080/projects/1/`
- **Action:** Type "Outstanding technical execution and great architecture!" and click "Post Comment". Then refresh page.
- **Expected Behavior:** Comment inserts immediately, persists to database, and remains visible upon hard refresh.
- **Success Condition:** Comment appears with author badge and timestamp.

---

### Phase 4: Certificates, Signed Records & Cryptographic Verification (T4)

#### Step 17 & 18: Certificate Generation & Retrieval
- **URL / Command:**
  ```bash
  curl -s -X POST http://localhost:8080/api/t4/certificates/ \
    -H "Cookie: session=org_7f2a" \
    -H "Content-Type: application/json" \
    -d '{"event_id": 1, "recipient_name": "Alice Developer", "recipient_email": "alice@example.com", "award_title": "First Place Overall"}'
  ```
- **Action:** Organizer issues a hackathon certificate.
- **Expected Behavior:** Server returns HTTP 201 with certificate ID and award metadata.
- **Success Condition:** Certificate record is created and public retrieval `GET /api/t4/certificates/<id>/` returns HTTP 200 with certificate data.

#### Step 19: Generate Signed Judge Record
- **URL / Command:**
  ```bash
  curl -s -X POST http://localhost:8080/api/t4/judge-records/ \
    -H "Cookie: session=org_7f2a" \
    -H "Content-Type: application/json" \
    -d '{"event_id": 1, "judge_id": 2}'
  ```
- **Action:** Issue Ed25519-signed participation attestation for Judge A.
- **Expected Behavior:** Backend formats canonical RFC 8785 JSON payload, signs it using the Ed25519 private seed, and stores the signature.
- **Success Condition:** Returns HTTP 201 with `record_id`, Base64 signature, and payload.

#### Step 20: Public Verification Endpoint
- **URL:** `http://localhost:8080/api/verify/<record_id>/`
- **Action:** Send GET request to verification endpoint.
- **Expected Behavior:** Backend extracts public key, validates Ed25519 signature over canonical payload, and returns verification status.
- **Success Condition:** Response contains `{"valid": true, "algorithm": "Ed25519", "record_id": <id>}`.

#### Step 21: Offline Verification CLI
- **Command:**
  ```bash
  docker compose exec web python manage.py verify_judge_record <record_id>
  ```
- **Action:** Execute the offline verification management command.
- **Expected Behavior:** CLI reads stored payload and signature, loads Ed25519 public key, and prints verification outcome.
- **Success Condition:** Terminal prints: `[VALID] Record <record_id> signature is authentic.`

---

### Phase 5: Embeddable Gallery Widget (T4)

#### Step 22 & 23: Open Embed Widget & Verify Framing Relaxation
- **URL:** `http://localhost:8080/embed/gallery/1/`
- **Action:** Open embed route directly and inspect response headers and layout.
- **Expected Behavior:**
  - Lightweight, responsive gallery showcase renders in the browser.
  - Project title, track badge, summary, and repo links are present.
  - `X-Frame-Options` is absent/exempt; `Content-Security-Policy: frame-ancestors *` is present.
  - Standard routes (e.g. `/projects/`) retain `X-Frame-Options: DENY`.
- **Success Condition:** Widget renders cleanly inside an `<iframe>` test page or browser tab. Sensitive fields (judge scores, invite codes, voting tokens, passwords) are completely absent.

---

### Phase 6: Bulk Operations & OpenAPI Specification (T4 - Person B Scope)

#### Step 24: Bulk Export
- **URL:** `http://localhost:8080/api/export/bulk/`
- **Action:** Send GET request with organizer session cookie (`session=org_7f2a`).
- **Expected Behavior:** Server streams comprehensive JSON export containing events, tracks, teams, projects, rubric criteria, judge assignments, and scores.
- **Success Condition:** Returns HTTP 200 with structured JSON; all passwords, tokens, and secret invite codes are scrubbed.

#### Step 25 & 26: Dry-Run and Bulk Import
- **URL:** `http://localhost:8080/api/import/bulk/?dry_run=true`
- **Action:** POST exported payload with `?dry_run=true` flag.
- **Expected Behavior:** Full validation runs without persisting database writes.
- **Success Condition:** Returns HTTP 200 with `{"dry_run": true, "valid": true}` and zero persistent side-effects.

#### Step 27: OpenAPI Specification Endpoint
- **URL:** `http://localhost:8080/api/schema/` or `http://localhost:8080/api/openapi.json`
- **Action:** Navigate to the OpenAPI schema URL in browser.
- **Expected Behavior:** Returns valid OpenAPI 3.0.3 machine-readable documentation describing judging, voting, certificates, and export/import endpoints.
- **Success Condition:** HTTP 200 with valid JSON schema structure.
