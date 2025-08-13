# Leosac Web (Flask) – Admin Guide and Integration Manual

This guide explains how the Flask-based Leosac Web works, how to build and deploy it, and how to operate Users, Credentials, Groups, Schedules, Doors and Zones so that schedule mappings actually grant door access. It also documents the audit flow so you can interpret GRANTED/DENIED events on the dashboard and audit log.

## 1) How the web server works

- Flask app with Bootstrap templates and a persistent WebSocket client (`services/websocket_service.py`) that talks to Leosac.
- Auth: Flask-Login stores a session; we cache the Leosac auth token and user info and reuse it for WebSocket calls.
- Data flow:
  - UI pages render server-side; each route pulls live data from Leosac via the WebSocket client thread.
  - JSON endpoints provide lightweight data for the dashboard and audit views.

Key pieces:
- `app.py` – App bootstrap; session auth; some JSON routes (e.g., `/api/dashboard/summary`).
- `routes/` – Feature blueprints: `users.py`, `groups.py`, `credentials.py`, `doors.py`, `zones.py`, `schedules.py`, `audit.py`.
- `services/websocket_service.py` – Thread-safe interface to Leosac’s WebSocket API: get_users, get_credentials, get_groups, get_doors, get_audit_logs, get_audit_statistics, etc.
- `templates/` – UI pages including `index.html` (dashboard) and `auditlog.html`.

## 2) Build and run

Prereqs: Python 3.8+, a reachable Leosac server with WebSocket enabled.

Setup:
```bash
pip install -r requirements.txt
cp env.example .env
# edit .env:
# LEOSAC_ADDR=ws://<leosac-host>:8888
# SECRET_KEY=<random>
python app.py
```
Open http://localhost:5000 and log in using your Leosac credentials.

Production (example):
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
# Put Nginx/Apache in front; set LEOSAC_ADDR (wss:// if TLS at Leosac)
```

## 3) Implementing with Leosac (what you need configured)

At the Leosac side you need:
- Doors defined with aliases (e.g., `DOOR_RELAY`), reachable by the module.
- Schedules defined with timeframes.
- Schedule mappings that connect Schedules to one or more of: Users, Groups, Credentials, Doors.
- Credentials created (e.g., RFID cards) with the correct `card-id` and `nb-bits` matching your reader.

The web UI lets you manage these pieces; Leosac performs the auth decision. When a credential is presented, Leosac emits an audit AuthEvent with an outcome.

## 4) How auth decisions are made (door access)

Reference: `access-control/src/modules/auth/auth-db/AuthDBInstance.cpp`

High-level flow (simplified):
- When a card is presented, Leosac builds an AuthSource from the message; if RFID, it looks up the credential by `card_id` and `nb_bits` (ignoring “noise” bit-lengths).
- If the credential exists and is “valid” (validity window enabled and current), Leosac resolves the User owner (if any).
- Leosac reads all `ScheduleMapping`s. For each mapping:
  - If it includes the User (direct or via Group) OR includes the Credential ID, Leosac builds a SimpleAccessProfile.
  - Doors linked in the mapping are added to the profile, with the Schedule’s timeframes. If no doors are set in the mapping, the profile applies to “any door”.
- Leosac then checks `profile.isAccessGranted(now, target)` where target is the door alias (it also tries `my_leosac.<alias>` for compatibility). If a matching schedule allows access at the current time for the target, access is GRANTED.
- An AuthEvent is logged with `AUTH_GRANTED` or `AUTH_DENIED` in the event mask.

What this means operationally:
- To grant door access, you must connect Schedules to identities (User/Group/Credential) AND target Doors via a Schedule Mapping.
- If a mapping has no doors, it applies to any door (“global” access for the schedule window).
- If a credential has no valid schedule mapping to the target door at the time of use, access is denied.

## 5) Using the web interface (step-by-step)

1. Users
- Create Users who will operate doors or own credentials.
- Users can be placed in Groups for easier policy assignment.

2. Credentials
- Create RFID credentials with alias, `card-id` (hex pairs), and `nb-bits`.
- Optionally set the Owner (User). Ownership is helpful for audit visibility and group-based mapping through the user, but not strictly required for auth.

3. Groups
- Create Groups and add Users. Groups simplify granting access to many users via one mapping.

4. Schedules
- Define Schedules with timeframes (days/times). These define when access is allowed.

5. Doors
- Ensure Doors exist with correct aliases (the alias is the target used during auth decisions). The UI lists doors and their details.

6. Schedule Mappings (the glue)
- Create mappings that connect: Schedule ↔ (Users and/or Groups and/or Credentials) ↔ Doors.
- Examples:
  - Map “Business Hours” schedule to Group “Employees” and Doors “FrontDoor, BackDoor”.
  - Map “ServerRoom Hours” schedule to Credential 123 only and Door “ServerRoom”.
- If no doors are selected, the mapping applies to all doors.

7. Verify in Audit
- Go to Audit Log or Dashboard. Present the card at the door; you should see an AuthEvent with GRANTED when within schedule and mapped to the door; otherwise DENIED.

## 6) Dashboard and Audit

- Dashboard shows quick counts (users, groups, credentials, doors), recent AuthEvents, and totals (granted/denied/unique credentials).
- Audit tab offers filters by time, door, user, and access outcome.
- Outcomes are derived from the event mask (`AUTH_GRANTED`/`AUTH_DENIED`) or event type/description when present.

## 7) Help page in the UI

This documentation is also available under Help in the web interface. Open the Help page from the sidebar to read the same guidance in-app.

## 8) Troubleshooting

- Credential not found: verify `card-id` and `nb-bits`, and that the credential is enabled/valid.
- Granted/Denied unexpected: confirm a Schedule Mapping ties the identity (User/Group/Credential) to the target Door during the current time.
- Door alias mismatch: check the door alias in Leosac matches the one used during auth; the system also tries `my_leosac.<alias>`.
- Connection: set `LEOSAC_ADDR` correctly and ensure the WebSocket is reachable; see logs for errors.
