# Hospital Management System — Project Plan

| Item | Value |
|---|---|
| Version | Draft v2, for review |
| Pace | 5–8 hours/day, no fixed deadline |
| Delivery | Five phases, each released live before the next one starts |
| Repository | `hospital-management-system` (monorepo with `backend/` and `frontend/`) |
| Last updated | 2026-09-16 |

> **How to use this document.** This is the single source of truth for scope and technical decisions. Keep it in the repository as `docs/PROJECT_PLAN.md`. When a decision changes, update this file and record the reason in an ADR (`docs/adr/`). Work on one phase at a time: an idea that belongs to a later phase goes into the backlog, not into the current phase.

## What changed from v1

- **No deadline.** The 30-day limit, the cut rule, and the Must/Should/Won't split are gone. Work is organized into five phases without dates.
- **Nothing cut from your original idea.** The Manager, Customer Service, and Patient roles and the pharmacy branches are back. All former "Should have" items are part of Phase 1.
- **React frontend,** written by Claude Code and served from the same origin as the API.
- **Clear ownership (§14).** You own configuration, Alembic migrations, backend business logic, and backend tests. Claude Code owns CI/CD, documentation, and the frontend, and guides you through everything else.
- **Cookie-based refresh tokens from Phase 1,** because a browser app is now planned.
- Extra ideas that were never part of your original request, such as billing and labs, are listed as optional (§2).

## Contents

1. Vision and goals
2. Scope and phases
3. Roles
4. Workflows and state rules
5. User stories and acceptance criteria
6. Authorization model
7. Domain model
8. Key technical designs
9. Architecture and repository structure
10. Tech stack
11. API conventions and endpoint catalog
12. Security and non-functional requirements
13. Testing strategy
14. Working model: you and Claude Code
15. Environments, configuration, and CI/CD
16. Deployment plan
17. Documentation deliverables
18. Roadmap
19. Risks and mitigations
- Appendix A: Starter files
- Appendix B: Glossary

---

## 1. Vision and goals

**Problem.** In many hospitals, the front desk, the doctors, the branch pharmacies, and patient support work in disconnected tools. Prescriptions are re-typed, stock counts drift away from reality across branches, patients can't see their own records, and nobody can say who opened a patient's file.

**Vision.** One secure system that connects registration, scheduling, consultations, a multi-branch pharmacy, customer service, and a patient portal, where each person can do exactly what their role requires and every access to medical data is traceable.

**What the project must prove to an employer**

| # | Capability | Evidence in the project |
|---|---|---|
| G1 | Domain modeling | Real-world rules: time slots, stock batches with expiry dates, branch stock and transfers, support tickets, state machines |
| G2 | Security | Cookie-based refresh-token rotation, permission-based and record-level authorization, delegated administration, patient data isolation, audit trail |
| G3 | Data integrity | Constraints, row locks, and transactions that stay correct under concurrent requests |
| G4 | Engineering discipline | Automated tests, CI/CD, Docker, migrations, code review, ADRs, and an API client checked against the API contract |
| G5 | Delivery | Every phase released live and documented, with demo accounts |

**A phase is complete when**

- Its features work on the live URL with demo accounts: through the API docs in Phase 1, and through the web app from Phase 2 onward.
- Every new protected endpoint has authorization tests for allowed and denied roles.
- CI is green. Overall coverage stays at or above 80%, and permission, allocation, dispensing, and transfer code is fully covered.
- The README, ADRs, API docs, and code documentation are up to date, and the release is tagged.

---

## 2. Scope and phases

| Phase | Theme | Outcome | Release |
|---|---|---|---|
| 1 | Core hospital API | The staff workflow from registration to dispensing, tested and live | `v1.0.0` |
| 2 | Staff web app | A React app covering every Phase 1 role and feature | `v1.1.0` |
| 3 | Pharmacy branches | Multiple branches, branch-scoped stock, and transfers between branches | `v1.2.0` |
| 4 | Patient portal | Patients sign in, book appointments, and see their own records | `v1.3.0` |
| 5 | Customer service and management | Support tickets, operational reports, and delegated staff administration | `v1.4.0` |

From Phase 3 onward, each phase delivers its backend and its screens together.

### Phase 1: Core hospital API

| Module | Features |
|---|---|
| Auth | Login; cookie-based token refresh with rotation; logout; current user; change password; forced password change; login rate limiting |
| Staff administration | Admin creates, updates, deactivates, and reactivates accounts and resets passwords; a CLI command creates the first Admin |
| Organization | Departments; a branches table with one default branch; doctors belong to a department; pharmacists belong to a branch |
| Patients | Register, update, and search patients; auto-generated medical record number (MRN) |
| Appointments | Fixed 30-minute slots; available-slots lookup; booking protected against double-booking; list and filter; cancel; no-show; check-in |
| Clinical | Check-in opens a visit; vitals; notes, diagnosis, and completion; doctors read their own patients' history |
| Prescriptions | Issue a prescription with items during an open visit; cancel; pharmacist queue |
| Pharmacy | Medicine catalog; receiving batches with expiry date and unit cost; stock movement ledger; FEFO dispensing from the pharmacist's branch; stock adjustments with reasons; low-stock and expiring-stock reports |
| Audit | Audit entries for writes, logins, and sensitive reads; searchable by Admin |
| Platform | Health checks; one error format; pagination; request-ID logging; security headers; `seed-demo` with `--reset`; demo-account protection; complete OpenAPI docs |

### Phase 2: Staff web app

- A React and TypeScript app, built into the same Docker image and served by the API at the same origin.
- Sign-in, forced password change, session restore after a page reload, role-based navigation, and clear "no access" and "not found" pages.
- Screens for Admin, Receptionist, Nurse, Doctor, and Pharmacist covering every Phase 1 feature.
- A typed API client generated from the OpenAPI schema; CI fails if the client and the API drift apart.
- Component tests, and a Playwright end-to-end test of the core workflow.

### Phase 3: Pharmacy branches

- Admin manages branches and assigns pharmacists to them.
- Stock, dispensing, adjustments, and reports are scoped to the pharmacist's branch.
- Pharmacists check a medicine's availability across all branches.
- Stock transfers between branches: request, dispatch, receive, and cancel.
- Branch and transfer screens in the web app.

### Phase 4: Patient portal

- A Receptionist enables portal access; the patient activates it with a one-time code and chooses a password.
- Patients see their profile, upcoming and past appointments, completed visit summaries, and prescriptions.
- Patients book available slots and cancel their own appointments, within limits.
- Portal screens that work well on phones.

### Phase 5: Customer service and management

- Customer Service role: ticket inbox, assignment, replies, internal notes, and resolve, close, and reopen actions.
- Patients open tickets and reply from the portal; Customer Service can open a ticket on a patient's behalf.
- Manager role: operational reports with charts (appointments, no-shows, pharmacy, tickets) and administration of non-admin staff accounts.

### Optional ideas (not planned)

Billing and invoices, lab and radiology orders, wards and beds, email and SMS notifications with a background worker, ICD-10 diagnosis codes, allergy checks when prescribing, partial dispensing, file uploads, and multiple roles per user.

These stay in the backlog. To build one, plan it as a new phase after Phase 5.

---

## 3. Roles

| Role | Real-world person | Phase | Responsibilities |
|---|---|---|---|
| **Admin** | IT administrator | 1 | All accounts, departments, branches, and the audit log. **No access to medical records.** |
| **Receptionist** | Front desk | 1 | Patients, appointments, and check-in; enables patient portal access (Phase 4) |
| **Nurse** | Nursing staff | 1 | Checked-in queue and vitals |
| **Doctor** | Physician | 1 | Own schedule, consultations, prescriptions, and own patients' history |
| **Pharmacist** | Branch pharmacy | 1 | Medicine catalog, branch stock, and dispensing; transfers (Phase 3) |
| **Patient** | Patient | 4 | Own appointments, visit summaries, prescriptions, and tickets |
| **Customer Service** | Patient support | 5 | Tickets; reads patient contact details and appointments |
| **Manager** | Hospital management | 5 | Aggregated operational reports; manages non-admin staff accounts. **No access to medical records.** |

**Design rules**

- **No public sign-up.** Admins create any account. Managers create staff accounts for every role except Admin and Manager. Receptionists enable portal access for patients. The first Admin comes from a CLI command (`python -m app.cli create-admin`).
- **One role per user.** Multiple roles per user is an optional idea.
- **Patients are records first.** A patient record exists without a login; a portal account is optional and linked to the record.
- **Separation of duties.** Admin and Manager control accounts and see operations, never clinical data. Manager reports contain only aggregates, never patient identities.

---

## 4. Workflows and state rules

```mermaid
sequenceDiagram
    actor R as Receptionist
    actor N as Nurse
    actor D as Doctor
    actor P as Pharmacist
    participant API as HMS API
    R->>API: Register patient
    R->>API: Book appointment with a doctor
    R->>API: Check in patient (opens a visit)
    N->>API: Record vitals on the visit
    D->>API: Add notes and diagnosis
    D->>API: Issue prescription
    D->>API: Complete visit
    P->>API: List pending prescriptions at my branch
    P->>API: Dispense (stock deducted, earliest expiry first)
```

Any transition not listed below returns `409 Conflict`. Services enforce transitions and take row locks wherever two users could race.

### Appointment

| From | To | Who | Rules |
|---|---|---|---|
| — | `SCHEDULED` | Receptionist; Patient through the portal (Phase 4) | Starts on :00 or :30 and in the future; doctor is active; neither the doctor nor the patient has another active appointment at that time. Patients book up to 30 days ahead and hold at most 2 upcoming appointments |
| `SCHEDULED` | `CHECKED_IN` | Receptionist | Only on the appointment date (hospital timezone); creates an `OPEN` visit whose ID is returned on the appointment |
| `SCHEDULED` | `CANCELLED` | Receptionist; Patient (own appointment, at least 24 hours before the start) | Reason required; frees the slot |
| `SCHEDULED` | `NO_SHOW` | Receptionist | Only after the start time |
| `CHECKED_IN` | `COMPLETED` | System | When the doctor completes the visit |

### Visit

| From | To | Who | Rules |
|---|---|---|---|
| — | `OPEN` | System | Created at check-in |
| `OPEN` | `COMPLETED` | Assigned doctor | Diagnosis required; the visit becomes read-only |

Vitals, notes, and new prescriptions are accepted only while the visit is `OPEN`.

### Prescription

| From | To | Who | Rules |
|---|---|---|---|
| — | `ISSUED` | Assigned doctor | Visit is `OPEN`; at least one item; each medicine is active and listed once; quantity > 0 |
| `ISSUED` | `DISPENSED` | Pharmacist | Every item is fully covered by non-expired stock at the pharmacist's branch; all or nothing |
| `ISSUED` | `CANCELLED` | Issuing doctor | Reason required |

### Stock transfer (Phase 3)

| From | To | Who | Rules |
|---|---|---|---|
| — | `REQUESTED` | Pharmacist at the destination branch | Source and destination differ; at least one item; quantity > 0 |
| `REQUESTED` | `DISPATCHED` | Pharmacist at the source branch | Stock is taken earliest-expiry first from the source branch; all or nothing |
| `DISPATCHED` | `RECEIVED` | Pharmacist at the destination branch | Stock is added at the destination with the same batch numbers and expiry dates |
| `REQUESTED` | `CANCELLED` | Pharmacist at either branch | Reason required |

### Ticket (Phase 5)

| From | To | Who | Rules |
|---|---|---|---|
| — | `OPEN` | Patient through the portal; Customer Service on a patient's behalf | Category, subject, and first message required |
| `OPEN` | `IN_PROGRESS` | Customer Service | Assigned to an agent |
| `IN_PROGRESS` | `RESOLVED` | Assigned agent | Resolution message required |
| `RESOLVED` | `IN_PROGRESS` | Patient reply, or an agent | Within 7 days of resolution |
| `RESOLVED` | `CLOSED` | Customer Service | — |
| `OPEN` or `IN_PROGRESS` | `CLOSED` | Customer Service | Reason required, for example a duplicate |

### Portal access (Phase 4)

| Step | Who | Rules |
|---|---|---|
| Issue an activation code | Receptionist | The patient record has an email that no account uses yet; the code is random, single-use, and valid for 48 hours; a new code replaces the previous one |
| Activate the account | Patient | MRN and code match; the code locks after 5 failed attempts; creates a Patient account linked to the record, with the record's email as the login |
| Deactivate the account | Admin | Same rules as staff deactivation |

---

## 5. User stories and acceptance criteria

Each story becomes one GitHub issue titled with its ID, for example `APT-1: Book an appointment`.

### Phase 1

| ID | Role | Story |
|---|---|---|
| AUTH-1 | Staff member | Log in with email and password to use the tools for my role |
| AUTH-2 | Staff member | Stay signed in through token refresh, and end my session by logging out |
| AUTH-3 | Staff member | Change my password, and be required to replace a temporary one |
| AUTH-4 | Security | Slow down repeated failed login attempts |
| ADM-1 | Admin | Create a staff account with role, department, and branch |
| ADM-2 | Admin | Deactivate or reactivate an account, so access ends immediately |
| ADM-3 | Admin | Reset a user's password to a temporary one |
| ADM-4 | Admin | Manage departments |
| ADM-5 | Admin | Search the audit log to investigate who accessed or changed a record |
| PAT-1 | Receptionist | Register a patient and get an MRN |
| PAT-2 | Receptionist | Search patients by name, MRN, or phone to avoid duplicates |
| PAT-3 | Receptionist | Update a patient's details |
| APT-1 | Receptionist | Book a slot with a doctor without double-booking |
| APT-2 | Receptionist | See a doctor's available slots for a date |
| APT-3 | Receptionist | Cancel an appointment or mark a no-show |
| APT-4 | Receptionist | Check a patient in |
| APT-5 | Doctor | See my schedule for a day |
| CLN-1 | Nurse | See checked-in patients and record their vitals |
| CLN-2 | Doctor | Record notes and a diagnosis, then complete the visit |
| CLN-3 | Doctor | Read the past visits of patients I'm treating |
| RX-1 | Doctor | Issue a prescription during a visit |
| RX-2 | Doctor | Cancel a prescription that hasn't been dispensed |
| PHA-1 | Pharmacist | Manage the medicine catalog |
| PHA-2 | Pharmacist | Receive stock as batches with expiry dates and unit costs |
| PHA-3 | Pharmacist | See pending prescriptions and dispense them from my branch |
| PHA-4 | Pharmacist | Write off expired or damaged stock with a reason |
| PHA-5 | Pharmacist | See low-stock and expiring-stock reports |
| PLT-1 | Maintainer | Seed and reset demo data, with demo accounts protected from changes |

### Phase 2

| ID | Role | Story |
|---|---|---|
| WEB-1 | Staff member | Sign in, keep my session after a reload, and replace a temporary password in the app |
| WEB-2 | Staff member | See only the navigation and screens my role allows |
| WEB-3 | Admin | Manage accounts and departments, and search the audit log, in the app |
| WEB-4 | Receptionist | Search and register patients, book with a slot picker, and check patients in |
| WEB-5 | Nurse | Work from a checked-in queue and record vitals |
| WEB-6 | Doctor | Use a visit workspace with history, vitals, notes, diagnosis, and prescriptions |
| WEB-7 | Pharmacist | Work the prescription queue, dispense, receive and adjust stock, and view reports |
| WEB-8 | Maintainer | Keep the API client generated from OpenAPI and checked in CI |

### Phase 3

| ID | Role | Story |
|---|---|---|
| BR-1 | Admin | Create and update branches |
| BR-2 | Admin | Assign pharmacists to branches |
| BR-3 | Pharmacist | Manage and dispense only my branch's stock |
| BR-4 | Pharmacist | Check a medicine's availability across branches |
| TRF-1 | Pharmacist | Request stock from another branch |
| TRF-2 | Pharmacist | Dispatch a requested transfer from my branch |
| TRF-3 | Pharmacist | Receive a dispatched transfer at my branch |
| TRF-4 | Pharmacist | Cancel a transfer that hasn't been dispatched |

### Phase 4

| ID | Role | Story |
|---|---|---|
| POR-1 | Receptionist | Enable portal access and give the patient an activation code |
| POR-2 | Patient | Activate my account with the code and choose a password |
| POR-3 | Patient | See my upcoming and past appointments and visit summaries |
| POR-4 | Patient | See my prescriptions and whether they were dispensed |
| POR-5 | Patient | Book an available slot |
| POR-6 | Patient | Cancel my own appointment in time |

### Phase 5

| ID | Role | Story |
|---|---|---|
| TKT-1 | Patient | Open a ticket and reply from the portal |
| TKT-2 | Customer Service | Open a ticket on a patient's behalf |
| TKT-3 | Customer Service | Work an inbox: assign, filter, and prioritize tickets |
| TKT-4 | Customer Service | Reply to patients and add internal notes |
| TKT-5 | Customer Service | Resolve, close, and reopen tickets |
| MGR-1 | Manager | View appointment, pharmacy, and ticket reports |
| MGR-2 | Manager | Manage non-admin staff accounts |

### Acceptance criteria for the highest-risk stories

**APT-1: Book an appointment**

- **Given** an active doctor and a free slot, **when** the receptionist books it, **then** the API returns `201` and the appointment is `SCHEDULED`.
- **Given** the doctor already has an active appointment at that time, **when** anyone books the same slot, **then** the API returns `409`, even if both requests arrive at the same moment.
- **Given** a start time in the past or not on :00 or :30, **then** the API returns `422`.
- **Given** the caller isn't a Receptionist, **then** the API returns `403`.
- **Given** an appointment was cancelled, **then** its slot can be booked again.

**PHA-3: Dispense a prescription**

- **Given** an `ISSUED` prescription and enough non-expired stock at the pharmacist's branch, **when** the pharmacist dispenses it, **then**, in one transaction, stock is taken from the earliest-expiring batches first, one `DISPENSE` movement is recorded per batch used, the prescription becomes `DISPENSED`, and an audit entry is written.
- **Given** any item can't be fully covered, **then** the API returns `409` listing the short medicines, and no stock changes.
- **Given** the prescription is already `DISPENSED` or `CANCELLED`, **then** the API returns `409`.
- **Given** two pharmacists dispense the same prescription at the same moment, **then** exactly one succeeds.
- A batch quantity can never become negative; a database constraint enforces this.

**ADM-2: Deactivate an account**

- **When** an Admin deactivates a user, **then** all of that user's refresh tokens are revoked, and their next request with a still-valid access token returns `401`.
- **Given** a deactivated account, **when** it tries to log in, **then** the API returns `401` with the same generic message as a wrong password.
- **Given** an Admin tries to deactivate their own account, **then** the API returns `409`, so nobody locks the system out by mistake.
- The action is recorded in the audit log.

**TRF-2: Dispatch a transfer**

- **Given** a `REQUESTED` transfer and enough non-expired stock at the source branch, **when** a source-branch pharmacist dispatches it, **then**, in one transaction, stock is taken earliest-expiry first, one `TRANSFER_OUT` movement is recorded per batch, and the status becomes `DISPATCHED`.
- **Given** any item can't be fully covered, **then** the API returns `409` and no stock changes.
- **Given** the caller works at the destination branch, **then** the API returns `403`; **given** they work at an unrelated branch, **then** it returns `404`.
- **Given** two dispatch requests arrive at the same moment, **then** exactly one succeeds.
- Stock is conserved: source stock, plus stock in transit, plus destination stock stays the same through dispatch and receipt.

**POR-2: Activate a portal account**

- **Given** a valid, unexpired code and a matching MRN, **when** the patient activates with an acceptable password, **then** a Patient account linked to the record is created, the code is marked used, and the patient can log in.
- **Given** a used, expired, or replaced code, or a wrong MRN, **then** the API returns `400` with one generic message, so an attacker can't tell which part was wrong.
- **Given** 5 failed attempts for a code, **then** the code is locked, even if the correct code is entered afterward.
- The Receptionist never sees or sets the patient's password.

**MGR-2: Manage staff accounts as a Manager**

- **Given** a Manager, **when** they create a Nurse account, **then** the API returns `201`.
- **Given** a Manager, **when** they try to create a user with the Admin or Manager role, or promote a user to either role, **then** the API returns `403` and nothing changes.
- **Given** a Manager, **when** they try to update or deactivate an Admin or Manager account, **then** the API returns `404`.
- Every change is audited with the Manager as the actor.

---

## 6. Authorization model

### Principles

1. **Deny by default.** Every route is explicitly marked Public, Authenticated, or protected by a permission. A test fails if any route is missing this.
2. **Check permissions, not role names.** Code says `require_permission(Permission.PRESCRIPTIONS_DISPENSE)`, never `if user.role == "pharmacist"`.
3. **Two layers.** The route dependency answers *"may this role perform this kind of action?"* The service answers *"may this user touch this specific record?"*
4. **Hide what users can't access.** A record outside the user's scope returns `404`, not `403`, so IDs can't be probed. Together with principle 3, this prevents BOLA, the most common API security flaw.
5. **Trust the database, not the token.** The user's role and active status are loaded on every request, so role changes and deactivation take effect immediately.
6. **Patients use their own endpoints.** Patient features live under `/api/v1/portal` and always scope queries to the signed-in patient's record. Patients also sign in through `/auth` and read the shared directory (`directory:read`) to find doctors and free slots. Every other endpoint rejects the Patient role.
7. **The frontend isn't a security layer.** It hides screens a role can't use, but the API enforces every rule.

Roles and permissions are defined in code (`backend/app/core/permissions.py`) as enums plus a role-to-permissions mapping. They're version-controlled, reviewed, and tested like any other code (ADR-0003).

### Permission matrix

Columns: **Adm** Admin, **Mgr** Manager, **Rec** Receptionist, **Nur** Nurse, **Doc** Doctor, **Pha** Pharmacist, **CS** Customer Service, **Pat** Patient.

| Permission | Adm | Mgr | Rec | Nur | Doc | Pha | CS | Pat |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `users:manage` | ✅ | | | | | | | |
| `staff:manage` | | ✅ ⁶ | | | | | | |
| `departments:manage` | ✅ | | | | | | | |
| `branches:manage` | ✅ | | | | | | | |
| `audit:read` | ✅ | | | | | | | |
| `reports:read` | | ✅ | | | | | | |
| `directory:read` (departments, branches, doctors, free slots) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `patients:read` | | | ✅ | ✅ | ✅ ¹ | | ✅ | |
| `patients:write` | | | ✅ | | | | | |
| `portal:grant` | | | ✅ | | | | | |
| `appointments:read` | | | ✅ | ✅ | ✅ ² | | ✅ | |
| `appointments:manage` | | | ✅ | | | | | |
| `vitals:read` | | | | ✅ ³ | ✅ ¹ | | | |
| `vitals:write` | | | | ✅ ³ | | | | |
| `visits:read` | | | | | ✅ ¹ | | | |
| `visits:write` | | | | | ✅ ⁴ | | | |
| `prescriptions:read` | | | | | ✅ ⁴ | ✅ | | |
| `prescriptions:write` | | | | | ✅ ⁴ | | | |
| `prescriptions:dispense` | | | | | | ✅ ⁵ | | |
| `medicines:read` | | | | | ✅ | ✅ | | |
| `medicines:manage` | | | | | | ✅ | | |
| `stock:read` | | | | | | ✅ | | |
| `stock:manage` | | | | | | ✅ ⁵ | | |
| `tickets:read` | | | | | | | ✅ | |
| `tickets:manage` | | | | | | | ✅ | |
| `portal:self` | | | | | | | | ✅ ⁷ |

**Record-level rules**

1. Only patients with a *care relationship*: at least one non-cancelled appointment with this doctor.
2. Only the doctor's own appointments.
3. Only visits with status `OPEN`.
4. Only visits assigned to this doctor, and prescriptions this doctor issued.
5. Only stock at the pharmacist's own branch. Reading other branches' availability is allowed.
6. Only accounts with the Receptionist, Nurse, Doctor, Pharmacist, or Customer Service role. A Manager can never assign the Admin or Manager role.
7. Only the patient's own record, through `/portal` endpoints.

Pharmacists deliberately have no `patients:read`. A prescription response includes only the patient's name, MRN, and date of birth, which is enough to confirm identity at the counter. For the same reason, Manager reports never include patient names.

---

## 7. Domain model

### Design rules

- Primary keys are UUIDs.
- Every table has `created_at` and `updated_at` as timezone-aware UTC timestamps. The `HOSPITAL_TIMEZONE` setting is used only for rules such as "today" and slot boundaries.
- Status fields are Python enums stored as strings (`Enum(..., native_enum=False)`), which avoids difficult PostgreSQL enum migrations.
- Clinical, pharmacy, and ticket records are never hard-deleted; they change status. Users are deactivated, not deleted.
- Rules that must hold under concurrent requests live in the database: unique and partial indexes, CHECK constraints, and foreign keys.
- PostgreSQL doesn't index foreign keys automatically, so every foreign key and search column gets an explicit index.
- Money is stored as `NUMERIC(12, 2)` and handled as Python `Decimal`, never `float`.
- The schema is branch-aware from Phase 1: stock and pharmacists reference a branch, and Phase 1 runs with one default branch (ADR-0007).

### Entity relationships

```mermaid
erDiagram
    USERS ||--o| STAFF_PROFILES : "has"
    DEPARTMENTS ||--o{ STAFF_PROFILES : "groups doctors"
    BRANCHES ||--o{ STAFF_PROFILES : "employs pharmacists"
    USERS ||--o{ REFRESH_TOKENS : "owns"
    USERS ||--o{ AUDIT_LOGS : "performs"
    PATIENTS |o--o| USERS : "portal account"
    PATIENTS ||--o{ PORTAL_ACTIVATION_CODES : "receives"
    PATIENTS ||--o{ APPOINTMENTS : "books"
    USERS ||--o{ APPOINTMENTS : "attends as doctor"
    APPOINTMENTS ||--o| VISITS : "opens"
    VISITS ||--o{ VITAL_SIGNS : "records"
    VISITS ||--o{ PRESCRIPTIONS : "produces"
    PRESCRIPTIONS ||--|{ PRESCRIPTION_ITEMS : "contains"
    MEDICINES ||--o{ PRESCRIPTION_ITEMS : "prescribed as"
    BRANCHES ||--o{ STOCK_BATCHES : "holds"
    MEDICINES ||--o{ STOCK_BATCHES : "stocked as"
    STOCK_BATCHES ||--o{ STOCK_MOVEMENTS : "changed by"
    BRANCHES ||--o{ STOCK_TRANSFERS : "sends and receives"
    STOCK_TRANSFERS ||--|{ STOCK_TRANSFER_ITEMS : "contains"
    MEDICINES ||--o{ STOCK_TRANSFER_ITEMS : "moved as"
    PATIENTS ||--o{ TICKETS : "raises"
    TICKETS ||--|{ TICKET_MESSAGES : "contains"
    USERS ||--o{ TICKET_MESSAGES : "writes"
```

### Tables

`created_at` and `updated_at` are omitted below because every table has them.

| Table | Phase | Key columns | Constraints and notes |
|---|---|---|---|
| `users` | 1 | email, password_hash, full_name, role, is_active, must_change_password, is_demo, last_login_at | Email unique, stored lowercase |
| `staff_profiles` | 1 | user_id, department_id, branch_id, specialty, license_number, phone | One per staff user; department and specialty required for doctors; branch required for pharmacists |
| `departments` | 1 | name, is_active | Name unique |
| `branches` | 1 | code, name, address, phone, is_active | Code unique; Phase 1 seeds one default branch |
| `refresh_tokens` | 1 | user_id, token_hash, expires_at, revoked_at, replaced_by_id | Only the SHA-256 hash is stored |
| `patients` | 1 | mrn, first_name, last_name, date_of_birth, sex, phone, email, address, emergency_contact_name, emergency_contact_phone, user_id, created_by | MRN unique, generated from a PostgreSQL sequence (for example `MRN-000123`); `user_id` unique and nullable, used from Phase 4 |
| `portal_activation_codes` | 4 | patient_id, code_hash, expires_at, used_at, failed_attempts, created_by | At most one unused code per patient (partial unique index); locked at 5 failed attempts |
| `appointments` | 1 | patient_id, doctor_id, start_at, end_at, status, reason, cancellation_reason, booked_via, created_by | Partial unique indexes on (doctor_id, start_at) and (patient_id, start_at) where status isn't `CANCELLED`; CHECK that end_at is start_at plus 30 minutes |
| `visits` | 1 | appointment_id, patient_id, doctor_id, status, chief_complaint, notes, diagnosis, completed_at | `appointment_id` unique |
| `vital_signs` | 1 | visit_id, recorded_by, temperature_c, pulse_bpm, systolic_mmhg, diastolic_mmhg, respiratory_rate, spo2_percent, weight_kg, height_cm | CHECK constraints on realistic ranges |
| `medicines` | 1 | name, generic_name, form, strength, unit, reorder_level, is_active | Unique (name, form, strength) |
| `stock_batches` | 1 | branch_id, medicine_id, batch_number, expiry_date, unit_cost, quantity_received, quantity_on_hand, supplier, received_by | Unique (branch_id, medicine_id, batch_number); CHECK quantity_on_hand ≥ 0; index (branch_id, medicine_id, expiry_date) |
| `stock_movements` | 1 | batch_id, movement_type, quantity_delta, reason, prescription_item_id, transfer_item_id, performed_by | Append-only ledger. Types: `RECEIVE`, `DISPENSE`, `ADJUSTMENT` (Phase 1); `TRANSFER_OUT`, `TRANSFER_IN` (Phase 3) |
| `prescriptions` | 1 | visit_id, patient_id, doctor_id, status, cancellation_reason, dispensed_by, dispensed_branch_id, dispensed_at | Index (status, created_at) for the pharmacist queue |
| `prescription_items` | 1 | prescription_id, medicine_id, dosage, frequency, duration_days, quantity, instructions | Unique (prescription_id, medicine_id); CHECK quantity > 0 |
| `stock_transfers` | 3 | from_branch_id, to_branch_id, status, requested_by, dispatched_by, received_by, dispatched_at, received_at, cancelled_at, cancellation_reason | CHECK from_branch_id ≠ to_branch_id; indexes on (status, from_branch_id) and (status, to_branch_id) |
| `stock_transfer_items` | 3 | transfer_id, medicine_id, quantity | Unique (transfer_id, medicine_id); CHECK quantity > 0 |
| `tickets` | 5 | number, patient_id, created_by, assigned_to, category, priority, status, subject, resolved_at, closed_at, close_reason | Number unique, from a sequence (for example `TCK-000123`); index (status, assigned_to) |
| `ticket_messages` | 5 | ticket_id, author_id, body, is_internal | Internal notes are never returned to patients |
| `audit_logs` | 1 | actor_id, action, entity_type, entity_id, request_id, ip_address, details (JSONB) | Append-only; indexes on (entity_type, entity_id) and (actor_id, created_at) |

---

## 8. Key technical designs

### 8.1 Authentication and sessions

- **Login** uses the OAuth2 password form (the email goes in `username`), so the Authorize button in Swagger UI works. The response body contains the access token, and the refresh token is set as a cookie.
- **Passwords** are hashed with Argon2 through pwdlib. A wrong email and a wrong password return the same `401` message.
- **Access token:** an HS256 JWT signed with PyJWT, valid for 15 minutes, containing only `sub` (user ID), `iat`, and `exp`.
- **Refresh token:** a random opaque value, valid for 7 days. The database stores only its SHA-256 hash. It travels only in a cookie that is `HttpOnly`, `SameSite=Strict`, limited to `Path=/api/v1/auth`, and `Secure` in production.
- **Rotation and reuse detection:** each refresh revokes the old token and issues a new one. If a revoked token is used again, it may have been stolen, so every refresh token for that user is revoked.
- **Revocation:** logout revokes the current token and clears the cookie. Deactivation, password change, and password reset revoke all of the user's tokens.
- **Every request** loads the user from the database; inactive users get `401`.
- **Forced password change:** while `must_change_password` is set, every endpoint except `/auth/me`, `/auth/refresh`, `/auth/change-password`, and `/auth/logout` returns `403 PASSWORD_CHANGE_REQUIRED`. Refresh stays open so the web app can restore the session after a reload and show the change-password screen.
- **Rate limiting:** login and portal activation are limited per IP address and per account. The limiter is in memory, which is correct for a single instance; ADR-0004 notes that several instances would need a shared store such as Redis. Over the limit, the API returns `429 RATE_LIMITED`.
- **In the web app:** the access token lives in memory only, never in `localStorage`. After a page reload, the app calls `/auth/refresh`; on a `401`, it refreshes once and retries the request.
- **CSRF protection:** the web app and the API share one origin, and the refresh cookie is `SameSite=Strict`, so other websites can't make the browser send it. No CORS origins are configured in production.

### 8.2 Preventing double-booking

Checking for a conflict and then inserting isn't enough: two requests can both pass the check before either one inserts. The database must enforce the rule.

```python
# In the Appointment model's __table_args__
Index(
    "uq_appointments_doctor_slot",
    "doctor_id", "start_at",
    unique=True,
    postgresql_where=text("status <> 'CANCELLED'"),
),
Index(
    "uq_appointments_patient_slot",
    "patient_id", "start_at",
    unique=True,
    postgresql_where=text("status <> 'CANCELLED'"),
),
```

Every appointment is exactly one 30-minute slot, so "same doctor, same start time" means "overlap". The service inserts, catches `IntegrityError`, and raises a domain `ConflictError` that becomes `409`. Cancelled appointments don't count, so their slots can be booked again. Variable-length appointments would need a PostgreSQL exclusion constraint instead (ADR-0005).

For portal bookings, the service first locks the patient row (`SELECT … FOR UPDATE`) and then counts upcoming appointments, so two parallel requests can't both slip past the two-appointment limit.

### 8.3 Dispensing: all-or-nothing FEFO allocation

FEFO (first expired, first out) means taking stock from the batches that expire soonest. In one transaction:

1. Lock the prescription (`SELECT … FOR UPDATE`) and confirm it's still `ISSUED`.
2. Sort the items by `medicine_id`, so concurrent transactions always lock rows in the same order and can't deadlock.
3. For each item, lock the usable batches at the pharmacist's branch: `quantity_on_hand > 0` and `expiry_date > today`, ordered by `expiry_date`.
4. Pass the batches and required quantities to `allocate_fefo(...)`, a pure function with no database access. Unit-test it thoroughly.
5. If any medicine is short, roll back and return `409` with the shortages.
6. Otherwise, decrease each batch, insert a `DISPENSE` movement per batch used, mark the prescription `DISPENSED` with the branch, write the audit entry, and commit.

The `CHECK (quantity_on_hand >= 0)` constraint is the final safety net: even a bug in steps 3 to 6 can't produce negative stock.

Rule to record in ADR-0006: stock that expires today can't be dispensed.

### 8.4 Stock transfers

**Dispatch**, in one transaction:

1. Lock the transfer, confirm it's `REQUESTED`, and confirm the caller works at the source branch.
2. Sort the items by `medicine_id` and lock usable source batches, earliest expiry first.
3. Reuse `allocate_fefo(...)`. If any item is short, roll back and return `409`.
4. Decrease the source batches and insert one `TRANSFER_OUT` movement per batch, linked to the transfer item.
5. Mark the transfer `DISPATCHED`, write the audit entry, and commit.

**Receive**, in one transaction:

1. Lock the transfer, confirm it's `DISPATCHED`, and confirm the caller works at the destination branch.
2. For each `TRANSFER_OUT` movement, add the same quantity to the destination batch with the same medicine, batch number, expiry date, and unit cost. Use `INSERT … ON CONFLICT (branch_id, medicine_id, batch_number) DO UPDATE`, so an existing batch is topped up instead of duplicated.
3. Insert the matching `TRANSFER_IN` movements, mark the transfer `RECEIVED`, write the audit entry, and commit.

**Invariant to test:** for every medicine, stock on hand across all branches plus stock in transit equals total received minus total dispensed and adjusted.

### 8.5 Patient portal activation

- The code has 10 characters from an alphabet without look-alike characters (no `0`/`O` or `1`/`I`), generated with Python's `secrets` module. Only its SHA-256 hash is stored.
- The code is shown once to the Receptionist, expires after 48 hours, and works once. Issuing a new code invalidates the previous one.
- The service finds the code by MRN and compares hashes with `hmac.compare_digest`, which takes the same time whether or not the values match.
- 5 failed attempts lock the code, and the endpoint is rate-limited.
- Activation creates a Patient user whose login is the email on the patient record, links it through `patients.user_id`, and audits both the code issue and the activation.

### 8.6 Audit logging

- Services call `audit.record(actor, action, entity, details)` inside the same transaction as the change, so the audit entry and the change commit or roll back together.
- Recorded: every write, login success and failure, portal activation, and staff reads of clinical data (visits, vitals, and patient history). Patients reading their own records aren't audited.
- Never recorded: passwords, tokens, activation codes, or full clinical notes. Store IDs and changed field names instead.
- The table is append-only: no endpoint updates or deletes audit entries.
- Admins search with `GET /audit-logs`, filtering by actor, entity, action, and date.

### 8.7 Serving the web app

- A multi-stage `Dockerfile` builds `frontend/` with Node.js, then copies the built files into the Python runtime image.
- FastAPI registers `/api`, `/docs`, `/openapi.json`, and `/health` first. After those, it serves the built assets and returns `index.html` for any other `GET` path, so app routes still work after a page reload.
- A security-headers middleware sets `X-Content-Type-Options: nosniff`, a `Referrer-Policy`, and a `Content-Security-Policy` for web app pages that includes `frame-ancestors 'none'`.
- Locally, the Vite dev server proxies `/api` to `http://localhost:8000`, so the browser sees one origin and cookies behave exactly as in production (ADR-0010).

---

## 9. Architecture and repository structure

### Style

A modular monolith backend (FastAPI and PostgreSQL) plus a React single-page app, kept in one repository and deployed as one container (ADR-0001, ADR-0010).

**Backend modules:** `auth`, `users`, `organization`, `patients`, `appointments`, `clinical`, `prescriptions`, `pharmacy`, `portal`, `tickets`, `reports`, `audit`.

| Layer | File | Responsibility | Must not |
|---|---|---|---|
| Router | `router.py` | HTTP: parse input, call a service, return a response model | Contain business rules or queries |
| Schemas | `schemas.py` | Pydantic request and response models | Expose database models directly |
| Service | `service.py` | Business rules, record-level authorization, state transitions, audit calls, transaction boundary | Raise `HTTPException` or know about HTTP |
| Repository | `repository.py` | SQLAlchemy queries | Commit, or contain business rules |
| Models | `models.py` | SQLAlchemy tables and constraints | Contain business logic |

**Dependency rules**

- Routers depend on services; services depend on repositories and on other modules' services; repositories depend on models.
- A module never imports another module's repository.
- `portal` owns no tables; it composes other modules' services. `reports` has its own read-only repository with aggregate queries.
- `core/` depends on nothing inside `modules/`.

**Frontend rules**

- Code is organized by work area in `frontend/src/features/`. Pages compose components; data access happens only through TanStack Query hooks built on the generated client.
- Route guards mirror permissions for navigation only (principle 7 in §6).
- Forms use React Hook Form with Zod. API errors map from the standard error format to field and page messages.
- Screens are accessible by default: semantic HTML, labeled fields, keyboard support, and visible focus.

### Repository structure

```text
hospital-management-system/
├── backend/
│   ├── app/
│   │   ├── main.py                # App factory: routers, middleware, web app serving
│   │   ├── cli.py                 # create-admin, seed-demo, export-openapi
│   │   ├── core/
│   │   │   ├── config.py          # Settings from .env (yours)
│   │   │   ├── security.py        # Password hashing, JWT, refresh cookie
│   │   │   ├── permissions.py     # Role, Permission, ROLE_PERMISSIONS
│   │   │   ├── errors.py          # Domain exceptions and error codes
│   │   │   ├── logging.py         # Log setup and request-ID middleware
│   │   │   └── pagination.py
│   │   ├── db/                    # Declarative base, mixins, session
│   │   ├── api/                   # deps.py (get_db, get_current_user, require_permission), router.py
│   │   └── modules/
│   │       ├── auth/              # router.py, schemas.py, service.py, repository.py, models.py
│   │       ├── users/             # Users and staff profiles
│   │       ├── organization/      # Departments and branches
│   │       ├── patients/          # Patients and portal activation codes
│   │       ├── appointments/
│   │       ├── clinical/          # Visits and vital signs
│   │       ├── prescriptions/
│   │       ├── pharmacy/          # Medicines, batches, movements, dispensing, transfers, allocation.py
│   │       ├── portal/            # Patient endpoints composed from other services
│   │       ├── tickets/
│   │       ├── reports/           # Read-only aggregate queries
│   │       └── audit/
│   ├── migrations/                # Alembic (yours)
│   ├── tests/                     # unit/, integration/, conftest.py (yours)
│   ├── alembic.ini                # (yours)
│   ├── .env.example               # (yours)
│   ├── pyproject.toml
│   └── uv.lock
├── frontend/
│   ├── src/
│   │   ├── app/                   # Router, providers, layouts
│   │   ├── api/                   # Generated schema types, client, query hooks
│   │   ├── auth/                  # Session, refresh on 401, route guards
│   │   ├── features/              # admin, reception, nursing, doctor, pharmacy, portal, support, management
│   │   ├── components/            # Shared components; ui/ holds shadcn/ui components
│   │   └── lib/
│   ├── e2e/                       # Playwright tests
│   ├── openapi.json               # Exported from the backend for client generation
│   ├── package.json
│   └── vite.config.ts             # Dev proxy for /api
├── docs/
│   ├── PROJECT_PLAN.md
│   └── adr/
├── .claude/
│   └── settings.json
├── .github/
│   ├── workflows/ci.yml
│   ├── pull_request_template.md
│   └── dependabot.yml
├── Dockerfile                     # Builds the frontend, then the backend runtime image
├── docker-compose.yml             # PostgreSQL for development and end-to-end tests
├── entrypoint.sh                  # Runs migrations, then starts the server
├── render.yaml                    # Optional Render Blueprint
├── .gitignore
├── CLAUDE.md
└── README.md
```

---

## 10. Tech stack

### Backend

| Concern | Choice | Reason |
|---|---|---|
| Language | Python 3.13 | Mature and supported by every library used here |
| Web framework | FastAPI | Typed, fast, and generates OpenAPI docs |
| Validation | Pydantic v2 | Built into FastAPI |
| ORM | SQLAlchemy 2.x, typed `Mapped[...]` style | Industry standard |
| Database driver | psycopg 3 | Current PostgreSQL driver for Python |
| Migrations | Alembic | The standard companion to SQLAlchemy |
| Database | PostgreSQL 17 | Partial indexes, row locks, JSONB, and sequences |
| Settings | pydantic-settings | Typed configuration from environment variables |
| Password hashing | pwdlib with Argon2 | Modern hashing, recommended in FastAPI's docs |
| JWT | PyJWT | Maintained and simple |
| Package manager | uv | Fast and lockfile-based |
| Lint and format | Ruff and pre-commit | One fast tool, run before every commit and in CI |
| CLI | Typer | `create-admin`, `seed-demo`, and `export-openapi` commands |
| Tests | pytest, pytest-cov, FastAPI TestClient, Faker | Standard Python testing, with realistic fake data |

### Frontend

| Concern | Choice | Reason |
|---|---|---|
| Language | TypeScript, strict mode | Type errors are caught before the browser |
| Framework and build | React 19 and Vite | Standard, with a fast dev server and builds |
| Routing | React Router | Nested layouts and per-role route guards |
| Server state | TanStack Query | Caching, loading and error states, and retries |
| API client | openapi-typescript and openapi-fetch | Types generated from FastAPI's OpenAPI schema; no hand-written request types |
| Forms | React Hook Form and Zod | Fast forms with schema validation |
| UI | Tailwind CSS and shadcn/ui | Accessible components that live in the repository and stay editable |
| Charts (Phase 5) | Recharts | Straightforward React charts for reports |
| Tests | Vitest, React Testing Library, Playwright | Unit, component, and end-to-end tests |
| Code quality | ESLint and Prettier | Consistent, linted code |
| Tooling runtime | Node.js 24 LTS | Current long-term-support release |

### Shared

| Concern | Choice |
|---|---|
| Containers | Docker and Docker Compose |
| CI/CD | GitHub Actions, Render auto-deploy after checks pass, Dependabot |
| Hosting | Render web service and Neon PostgreSQL |
| AI tooling | Claude Code with project `CLAUDE.md`, settings, and skills |

**About ADR-0002.** FastAPI supports async code, but this project uses synchronous SQLAlchemy: it's simpler to learn and test, a single worker handles the expected load, and FastAPI runs plain `def` routes in a thread pool.

---

## 11. API conventions and endpoint catalog

### Conventions

- **Base path:** `/api/v1`. A breaking change would introduce `/api/v2`.
- **Resources:** plural, kebab-case nouns such as `/stock-batches`. State changes use action endpoints such as `POST /appointments/{id}/check-in`.
- **Fields:** JSON in `snake_case`; timestamps in ISO 8601 UTC with `Z`; dates as `YYYY-MM-DD`.
- **Lists:** `?page=1&size=20` (maximum 100), returning `{"items": [...], "total": 0, "page": 1, "size": 20}`.
- **Filters:** query parameters, for example `GET /appointments?doctor_id=...&date=2026-10-01&status=SCHEDULED`.
- **Errors:** one format for everything.

```json
{
  "error": {
    "code": "APPOINTMENT_SLOT_TAKEN",
    "message": "The doctor already has an appointment at this time.",
    "details": [],
    "request_id": "7f3c2a9e-..."
  }
}
```

| Status | Meaning |
|---|---|
| `200` / `201` / `204` | Success |
| `400` | The request can't be processed, for example an invalid activation code |
| `401` | Not authenticated, or the token is invalid or expired |
| `403` | Authenticated but missing the permission, or a password change is required |
| `404` | Doesn't exist, or is outside the user's scope |
| `409` | Business conflict: slot taken, invalid state change, insufficient stock |
| `422` | Validation error |
| `429` | Too many requests |

Standard error codes: `VALIDATION_ERROR`, `AUTHENTICATION_FAILED`, `PERMISSION_DENIED`, `PASSWORD_CHANGE_REQUIRED`, `NOT_FOUND`, `INVALID_STATUS_TRANSITION`, `APPOINTMENT_SLOT_TAKEN`, `INSUFFICIENT_STOCK`, `ACTIVATION_FAILED`, `RATE_LIMITED`.

**OpenAPI:** every route has a summary, a module tag, a response model, and its documented error responses, and the main request bodies include examples.

### Endpoint catalog

All paths are under `/api/v1`, except the health checks.

**System**

| Method | Path | Access | Phase |
|---|---|---|---|
| GET | `/health/live` | Public | 1 |
| GET | `/health/ready` | Public; checks the database | 1 |

**Auth**

| Method | Path | Access | Phase |
|---|---|---|---|
| POST | `/auth/login` | Public | 1 |
| POST | `/auth/refresh` | Public, with the refresh cookie | 1 |
| POST | `/auth/logout` | Authenticated | 1 |
| GET | `/auth/me` | Authenticated | 1 |
| POST | `/auth/change-password` | Authenticated | 1 |
| POST | `/auth/activate` | Public, with an activation code | 4 |

**Accounts and organization**

| Method | Path | Access | Phase |
|---|---|---|---|
| POST | `/users` | `users:manage`, or `staff:manage` ⁶ | 1 (Manager: 5) |
| GET | `/users` | `users:manage`, or `staff:manage` ⁶ | 1 (Manager: 5) |
| GET | `/users/{user_id}` | `users:manage`, or `staff:manage` ⁶ | 1 (Manager: 5) |
| PATCH | `/users/{user_id}` | `users:manage`, or `staff:manage` ⁶ | 1 (Manager: 5) |
| POST | `/users/{user_id}/deactivate` | `users:manage`, or `staff:manage` ⁶ | 1 (Manager: 5) |
| POST | `/users/{user_id}/activate` | `users:manage`, or `staff:manage` ⁶ | 1 (Manager: 5) |
| POST | `/users/{user_id}/reset-password` | `users:manage`, or `staff:manage` ⁶ | 1 (Manager: 5) |
| GET | `/departments` | `directory:read` | 1 |
| POST | `/departments` | `departments:manage` | 1 |
| PATCH | `/departments/{department_id}` | `departments:manage` | 1 |
| GET | `/branches` | `directory:read` | 1 |
| POST | `/branches` | `branches:manage` | 3 |
| PATCH | `/branches/{branch_id}` | `branches:manage` | 3 |
| GET | `/doctors` | `directory:read` | 1 |
| GET | `/doctors/{doctor_id}/available-slots?date=` | `directory:read` | 1 |
| GET | `/audit-logs` | `audit:read` | 1 |

**Patients**

| Method | Path | Access | Phase |
|---|---|---|---|
| POST | `/patients` | `patients:write` | 1 |
| GET | `/patients?q=` | `patients:read` | 1 |
| GET | `/patients/{patient_id}` | `patients:read` | 1 |
| PATCH | `/patients/{patient_id}` | `patients:write` | 1 |
| GET | `/patients/{patient_id}/visits` | `visits:read` ¹ | 1 |
| POST | `/patients/{patient_id}/portal-access` | `portal:grant` | 4 |

**Appointments**

| Method | Path | Access | Phase |
|---|---|---|---|
| POST | `/appointments` | `appointments:manage` | 1 |
| GET | `/appointments` | `appointments:read` | 1 |
| GET | `/appointments/{appointment_id}` | `appointments:read` | 1 |
| POST | `/appointments/{appointment_id}/check-in` | `appointments:manage` | 1 |
| POST | `/appointments/{appointment_id}/cancel` | `appointments:manage` | 1 |
| POST | `/appointments/{appointment_id}/no-show` | `appointments:manage` | 1 |

**Clinical**

| Method | Path | Access | Phase |
|---|---|---|---|
| GET | `/visits?status=OPEN` | `vitals:read` ³ or `visits:read` ¹ | 1 |
| GET | `/visits/{visit_id}` | `visits:read` ¹ or `vitals:read` ³ | 1 |
| POST | `/visits/{visit_id}/vitals` | `vitals:write` ³ | 1 |
| PATCH | `/visits/{visit_id}` | `visits:write` ⁴ | 1 |
| POST | `/visits/{visit_id}/complete` | `visits:write` ⁴ | 1 |

**Prescriptions**

| Method | Path | Access | Phase |
|---|---|---|---|
| POST | `/visits/{visit_id}/prescriptions` | `prescriptions:write` ⁴ | 1 |
| GET | `/prescriptions?status=ISSUED` | `prescriptions:read` | 1 |
| GET | `/prescriptions/{prescription_id}` | `prescriptions:read` | 1 |
| POST | `/prescriptions/{prescription_id}/cancel` | `prescriptions:write` ⁴ | 1 |
| POST | `/prescriptions/{prescription_id}/dispense` | `prescriptions:dispense` ⁵ | 1 |

**Pharmacy**

| Method | Path | Access | Phase |
|---|---|---|---|
| GET | `/medicines` | `medicines:read` | 1 |
| POST | `/medicines` | `medicines:manage` | 1 |
| GET | `/medicines/{medicine_id}` | `medicines:read` | 1 |
| PATCH | `/medicines/{medicine_id}` | `medicines:manage` | 1 |
| GET | `/medicines/{medicine_id}/availability` | `stock:read` | 3 |
| GET | `/stock-batches?medicine_id=&branch_id=` | `stock:read` | 1 |
| POST | `/stock-batches` | `stock:manage` ⁵ | 1 |
| POST | `/stock-batches/{batch_id}/adjustments` | `stock:manage` ⁵ | 1 |
| GET | `/pharmacy/reports/low-stock` | `stock:read` | 1 |
| GET | `/pharmacy/reports/expiring?days=30` | `stock:read` | 1 |
| POST | `/stock-transfers` | `stock:manage` ⁵ | 3 |
| GET | `/stock-transfers` | `stock:read` | 3 |
| GET | `/stock-transfers/{transfer_id}` | `stock:read` | 3 |
| POST | `/stock-transfers/{transfer_id}/dispatch` | `stock:manage` ⁵ | 3 |
| POST | `/stock-transfers/{transfer_id}/receive` | `stock:manage` ⁵ | 3 |
| POST | `/stock-transfers/{transfer_id}/cancel` | `stock:manage` ⁵ | 3 |

**Portal** (Patient only, `portal:self` ⁷)

| Method | Path | Phase |
|---|---|---|
| GET | `/portal/profile` | 4 |
| GET | `/portal/appointments` | 4 |
| POST | `/portal/appointments` | 4 |
| POST | `/portal/appointments/{appointment_id}/cancel` | 4 |
| GET | `/portal/visits` | 4 |
| GET | `/portal/prescriptions` | 4 |
| GET | `/portal/tickets` | 5 |
| POST | `/portal/tickets` | 5 |
| GET | `/portal/tickets/{ticket_id}` | 5 |
| POST | `/portal/tickets/{ticket_id}/messages` | 5 |

**Tickets** (Phase 5)

| Method | Path | Access |
|---|---|---|
| GET | `/tickets` | `tickets:read` |
| POST | `/tickets` | `tickets:manage` |
| GET | `/tickets/{ticket_id}` | `tickets:read` |
| POST | `/tickets/{ticket_id}/messages` | `tickets:manage` |
| POST | `/tickets/{ticket_id}/assign` | `tickets:manage` |
| POST | `/tickets/{ticket_id}/resolve` | `tickets:manage` |
| POST | `/tickets/{ticket_id}/close` | `tickets:manage` |
| POST | `/tickets/{ticket_id}/reopen` | `tickets:manage` |

**Reports** (Phase 5, `reports:read`)

| Method | Path |
|---|---|
| GET | `/reports/appointments?from=&to=` |
| GET | `/reports/pharmacy?from=&to=&branch_id=` |
| GET | `/reports/tickets?from=&to=` |

---

## 12. Security and non-functional requirements

### Security checklist

Check every item before each release.

- [ ] Passwords are hashed with Argon2, at least 12 characters long, and never logged or returned
- [ ] Access tokens expire in 15 minutes; refresh tokens are hashed, rotated, revocable, and sent only in an `HttpOnly`, `SameSite=Strict` cookie that is `Secure` in production
- [ ] The web app keeps access tokens in memory only, never in `localStorage`
- [ ] Every route is Public, Authenticated, or permission-protected, verified by the route guard test
- [ ] Record-level rules are enforced in services and tested; out-of-scope records return `404`
- [ ] Managers can't create, promote, or modify Admin or Manager accounts (tested)
- [ ] Patients reach only their own data (tested with two patients)
- [ ] Login and portal activation are rate-limited, with generic error messages
- [ ] Activation codes are random, hashed, single-use, expiring, and locked after 5 failed attempts
- [ ] All SQL goes through SQLAlchemy with bound parameters
- [ ] Inputs have limits: string lengths, numeric ranges, and a page-size cap
- [ ] Production runs on one origin with no CORS origins configured
- [ ] Security headers are set, including a Content-Security-Policy for web app pages
- [ ] Secrets live only in environment variables; `.env` is git-ignored and blocked from Claude Code; `.env.example` is committed
- [ ] Production error responses never include stack traces
- [ ] HTTPS in production; the container runs as a non-root user
- [ ] Dependabot is enabled for Python, npm, Docker, and GitHub Actions
- [ ] The database contains only generated demo data, never real patient information
- [ ] Public API docs in production are a documented portfolio exception (ADR-0009)

### Non-functional requirements

| Area | Requirement |
|---|---|
| Performance | Lists are paginated; no N+1 queries (use `selectinload`); indexes on foreign keys and search columns; web app routes are code-split |
| Reliability | The readiness check tests the database; migrations run before the server starts; `pool_pre_ping` replaces dropped connections |
| Observability | One structured log line per request with request ID, user ID, method, path, status, and duration; an `X-Request-ID` response header |
| Accessibility | Keyboard-operable screens, labeled form fields, visible focus, and sufficient contrast, targeting WCAG 2.2 AA |
| Usability | Staff screens are designed for desktop; portal screens also work on phones |
| Maintainability | Ruff and ESLint pass; Python type hints and strict TypeScript; detailed docstrings on every module, class, and function |
| Privacy | Least-privilege roles, audited staff reads, aggregated manager reports, and no personal data in logs |

---

## 13. Testing strategy

### Who writes which tests

| Tests | Written by | Claude Code's role |
|---|---|---|
| Backend unit, integration, and workflow tests (pytest) | You | Explains the pytest features you need, suggests edge cases before you start, and reviews your tests |
| Frontend component tests (Vitest and React Testing Library) | Claude Code | Writes and maintains them |
| End-to-end tests (Playwright) | Claude Code | Writes and maintains them; you review the scenarios |

### Backend test levels

| Level | What it covers | Examples |
|---|---|---|
| Unit | Pure functions with no database | `allocate_fefo`, slot generation, token hashing, permission mapping, activation code generation |
| Integration | API plus a real PostgreSQL database | Every endpoint: success, validation, `401`, `403`, `404`, `409` |
| Workflow | A full business flow through the API | Register, book, check in, vitals, prescribe, dispense; request, dispatch, receive a transfer |

### Rules

- Tests run against PostgreSQL, never SQLite, because the design depends on partial indexes, row locks, and sequences.
- Each test runs inside an outer transaction that is rolled back afterward, using SQLAlchemy's "join a session into an external transaction" pattern (`join_transaction_mode="create_savepoint"`), so services can still call `commit()`.
- Factory fixtures create users with any role, patients, medicines, batches, and branches, with Faker data.
- **Authorization matrix test:** a parametrized test sends a request to each protected endpoint as each role and checks for `403` wherever §6 denies access.
- **Route guard test:** fails if any route isn't marked Public, Authenticated, or permission-protected.
- **Isolation tests:** two patients, two doctors, and two branches confirm every record-level rule in §6.
- **Delegated administration tests:** confirm the Manager rules in MGR-2.
- **Concurrency tests:** two threads book the same slot, dispense the same prescription, or dispatch the same transfer; exactly one succeeds.
- **Conservation test:** stock totals stay consistent across dispensing, adjustments, and transfers.
- **Contract check:** CI regenerates the web client from the OpenAPI schema and fails if anything changed.
- **Bug rule:** every bug fix comes with a test that fails before the fix.
- Coverage: at least 80% overall; permission, allocation, dispensing, and transfer code fully covered.

### Edge-case checklist

Claude Code uses this list to suggest edge cases before you write tests. For every endpoint, consider:

- **Authentication:** no token, expired token, deactivated user, pending forced password change.
- **Permission:** every role without the permission gets `403`.
- **Record scope:** another doctor's, branch's, or patient's record gets `404`.
- **Validation boundaries:** empty strings, maximum lengths, zero and negative numbers, past and far-future dates, invalid enum values, malformed IDs.
- **Time:** slot boundaries, "today" in the hospital timezone, and stock expiring exactly today.
- **State:** every transition that §4 doesn't allow.
- **Concurrency:** the same action submitted twice at the same moment.
- **Repetition:** repeating a completed action, such as dispensing or cancelling twice.
- **Pagination and filters:** empty results, a page beyond the end, and sizes 0 and 101.
- **Audit:** the expected audit entry exists and contains no secrets.

### End-to-end scenarios

| Phase | Scenario |
|---|---|
| 2 | The receptionist books and checks in, the nurse records vitals, the doctor prescribes, and the pharmacist dispenses |
| 3 | Branch A requests stock, Branch B dispatches it, and Branch A receives it |
| 4 | A patient activates an account, books a slot, and sees a dispensed prescription |
| 5 | A patient opens a ticket; an agent replies and resolves it; the patient reopens it |

---

## 14. Working model: you and Claude Code

### Who does what

| Area | You | Claude Code |
|---|---|---|
| Libraries | Run the install commands; ask for details when you want them | Names each library you need with a one-line purpose and its install command; explains each import in one line (what it is and how it helps here); goes deeper only when asked |
| Configuration: `backend/.env`, `backend/.env.example`, `backend/app/core/config.py` | Write | Guides and reviews; can't edit these files |
| Migrations: `backend/alembic.ini`, `backend/migrations/` | Write, generate, review, and apply | Guides and reviews; can't edit these files or run `alembic revision` |
| Backend business logic | Write | Mentors with questions and hints, reviews, and fixes code only when you ask, explaining why |
| Backend tests (pytest) | Write | Explains the pytest features you need, suggests edge cases before you start, and reviews |
| CI/CD: GitHub Actions, Dependabot, Docker, Compose, Render Blueprint | Understand each step | Writes and maintains; reads failed runs with the GitHub CLI |
| Documentation: detailed docstrings, one-line import comments, README, OpenAPI text | Review | Writes and keeps it up to date (§17) |
| ADRs | Explain each decision in your own words | Writes the ADR from your explanation for you to approve |
| React frontend and its tests | Try it in the browser and report problems | Writes and maintains |

### How Claude Code explains libraries

Short by default. For example:

```text
Install: uv add pydantic-settings
  pydantic-settings: loads environment variables and .env files into a validated class.

Imports:
  BaseSettings: base class whose fields are filled from the environment.
  SettingsConfigDict: typed options, such as which .env file to read.
  SecretStr: hides a secret's value when it's printed or logged.
```

Say "details", "explain more", or "why" when you want the long version. When Claude Code documents the code, the same one-line explanation becomes the import's comment (§17).

### Feature loop

1. Pick the next issue on the board.
2. In plan mode, ask Claude Code which libraries the feature needs and which edge cases to cover.
3. Write the tests yourself.
4. Write the settings, migration, and business logic yourself. Ask Claude Code for hints when you're stuck.
5. Run the tests, ask Claude Code for a review, and fix the findings yourself.
6. Claude Code adds detailed docstrings and one-line import comments, and updates the README and OpenAPI text. You review them.
7. From Phase 2 onward, Claude Code builds the matching screens, and you try them in the browser.
8. Write the pull request description in your own words, and merge when CI passes.

### Ownership rules

- Never commit backend code you can't explain line by line.
- For code Claude Code writes (frontend, CI/CD, docs), understand what each part does and why it exists.
- The README says clearly which parts you wrote and which parts Claude Code wrote.

### Git and GitHub

- **Board:** GitHub Projects with the columns Backlog, Ready, In Progress, In Review, and Done. One issue per story or technical task, and one GitHub milestone per plan milestone.
- **Branches:** `main` is always deployable and protected by a ruleset that requires pull requests and passing CI (no required approvals, since you work alone). Branch names: `feat/apt-1-book-appointment`, `fix/...`, `test/...`, `docs/...`, `chore/...`.
- **Commits:** Conventional Commits, for example `feat(appointments): prevent double booking with partial unique index`.
- **Pull requests:** one feature per pull request, ideally under about 400 changed lines, squash-merged into `main`. The pull request template contains the Definition of Done.
- **Releases:** a tag with short release notes at the end of each milestone (§18).

### Definition of Done (every issue)

- [ ] Acceptance criteria met
- [ ] Tests cover success, validation, permission, record-level, and conflict cases
- [ ] Migration written and reviewed, if the schema changed
- [ ] Linters and tests pass locally and in CI
- [ ] OpenAPI summary, tag, response model, and error responses documented
- [ ] Detailed docstrings and one-line import comments added; README and docs updated where behavior changed
- [ ] Claude Code review completed and findings resolved
- [ ] You can explain every backend change without notes
- [ ] Merged and successfully deployed

### Claude Code setup

- **Start Claude Code from the repository root.** Project settings load from the folder where a session starts, and the path rules below are resolved from it.
- **`CLAUDE.md`:** the collaboration rules and conventions, loaded at the start of every session.
- **`.claude/settings.json`:** deny rules that stop Claude Code from reading `backend/.env`, from editing your configuration and migration files, and from running `alembic revision`; it also asks for your approval before `alembic upgrade` or `downgrade`. Claude Code enforces these rules on its own tools and on recognized shell file commands, but a program it runs (such as a Python script) can still open files, so treat them as a guard rail, not a sandbox.
- **Plan mode** before each feature: Claude Code reads files and proposes an approach without editing source files.
- **Learning output style (optional):** for extra practice, Claude Code leaves small parts of the code for you to write.

---

## 15. Environments, configuration, and CI/CD

### Environments

| Environment | Backend | Frontend | Database |
|---|---|---|---|
| Local | `uv run fastapi dev app/main.py` in `backend/` | `npm run dev` in `frontend/`, proxying `/api` to the backend | PostgreSQL 17 in Docker Compose |
| CI | GitHub Actions | GitHub Actions | PostgreSQL 17 service container |
| Production | One Render web service running the Docker image | Built into the same image | Neon PostgreSQL |

### Configuration

You create these settings in `backend/.env` and load them in `backend/app/core/config.py`. Production values are set in the Render dashboard.

| Variable | Example | Notes |
|---|---|---|
| `ENVIRONMENT` | `local`, `test`, or `production` | Controls error detail and the cookie's `Secure` flag |
| `DATABASE_URL` | `postgresql+psycopg://hms:hms@localhost:5432/hms` | Must start with `postgresql+psycopg://` (the settings validator checks it). In production, use Neon's connection string with its `postgresql://` prefix changed to `postgresql+psycopg://`, keeping `sslmode=require` |
| `JWT_SECRET_KEY` | *(64 hex characters)* | At least 32 characters and different in every environment; generate with `uv run python -c "import secrets; print(secrets.token_hex(32))"` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | |
| `HOSPITAL_TIMEZONE` | `Europe/London` | IANA timezone name used for "today" and slot rules |
| `CORS_ORIGINS` | *(empty)* | Comma-separated; stays empty because the web app and API share one origin |
| `LOG_LEVEL` | `INFO` | |
| `DEMO_MODE` | `true` in production | Turns on demo-account protection |
| `WEB_DIST_DIR` | *(empty locally)* | Phase 2: folder of the built web app inside the container; empty turns serving off |

### CI pipeline (`.github/workflows/ci.yml`)

Runs on every pull request and every push to `main`.

| Job | From phase | Steps |
|---|---|---|
| `backend` | 1 | `uv sync --locked`; Ruff lint and format check; PostgreSQL service; `alembic upgrade head`; `alembic check`; `pytest --cov=app --cov-fail-under=80` |
| `image` | 1 | Build the production Docker image |
| `frontend` | 2 | `npm ci`; ESLint; type check; Vitest; production build |
| `api-contract` | 2 | Export the OpenAPI schema, regenerate the client types, and fail if anything changed |
| `e2e` | 2 | Start the app and database with Docker Compose, seed demo data, and run Playwright |

`alembic check` fails when the models and migrations don't match, which catches a forgotten migration.

### Continuous deployment

In Render, set auto-deploy to **After CI Checks Pass**. When a commit reaches `main`, Render waits for the GitHub Actions checks and deploys only if they pass. If a build fails, the previous version stays live.

### How Claude Code handles CI/CD

- Writes and maintains every workflow, Dependabot, Docker, and Render file, with a one-line explanation of each job or step it adds.
- Diagnoses failures with `gh run list` and `gh run view <run-id> --log-failed`.
- Never writes secrets into files. It tells you which GitHub Actions secret or Render environment variable to add.

---

## 16. Deployment plan

### Target architecture

```mermaid
flowchart LR
    Dev[You] -->|push and pull request| GH[GitHub]
    GH --> CI[GitHub Actions: backend, frontend, contract, e2e, image]
    CI -->|checks pass| R[Render web service: FastAPI serves the API and the React app]
    R -->|TLS| N[(Neon PostgreSQL)]
    U[Staff, patients, recruiters] -->|HTTPS| R
```

### Why Render and Neon

- **Render** builds the Docker image straight from GitHub, provides HTTPS, and can wait for CI before deploying.
- **Render's free PostgreSQL isn't suitable** for a demo that must stay online: free Render databases expire 30 days after creation.
- **Neon's free plan doesn't expire.** Its limits (0.5 GB of storage and 100 compute-hours per month per project) are far above this project's needs.
- **Known trade-off (state it in the README):** a free Render web service spins down after 15 minutes without traffic and needs about a minute to wake up, and Neon's free compute suspends after 5 minutes idle. The first request after a quiet period is slow; later requests are normal.
- **Upgrade path:** Render's smallest paid instance removes spin-down. Because the app is containerized, changing hosts is a configuration change, not a rewrite.

Free-tier terms change over time, so re-check both providers' current limits before deploying.

### Production container

- A multi-stage `Dockerfile`: a Node.js 24 stage builds `frontend/`, a uv stage installs backend dependencies from `uv.lock`, and the final slim Python 3.13 image copies the backend and the built web app and runs as a non-root user.
- `entrypoint.sh` runs `alembic upgrade head`, then `fastapi run app/main.py --port ${PORT} --workers 1`. Render provides `PORT`.
- Running migrations at startup is safe with one instance. With several instances, migrations would move to a separate release step (ADR-0008).
- The SQLAlchemy engine uses `pool_pre_ping=True` and a small pool (for example, 5 connections), so connections dropped while Neon was suspended are replaced automatically.
- Optional: describe the service in a `render.yaml` Blueprint so the infrastructure is versioned with the code.

### First deployment checklist (Phase 1, Milestone 1.2)

1. Create a Neon project in the region closest to your Render region, and copy the direct (non-pooled) connection string.
2. Create a Render web service from the GitHub repository using the Dockerfile. Set the health check path to `/health/ready` and auto-deploy to After CI Checks Pass.
3. Add the environment variables in the Render dashboard, never in the repository.
4. Deploy, then confirm that `/health/ready` returns `200` and `/docs` loads.
5. Create the first Admin by running the CLI on your machine against the Neon connection string. Set that URL only in your terminal session, never in a file.
6. Log in through Swagger UI on the live URL, then tag `v0.1.0`.

### Demo data by phase

| Phase | `seed-demo` adds |
|---|---|
| 1 | One account per staff role, departments, the default branch, about 30 patients, about 25 medicines with batches (some low, some near expiry), past visits with dispensed prescriptions, and upcoming appointments |
| 3 | Two more branches with their own stock, and a transfer in each status |
| 4 | A demo patient with portal access, appointments, and prescriptions |
| 5 | Customer Service and Manager accounts, and tickets in each status |

`seed-demo --reset` restores everything, and demo accounts can't be deactivated or have their passwords changed. The README lists demo credentials for each role and a short guided tour for each phase.

---

## 17. Documentation deliverables

### README.md (the project's front page)

1. One-paragraph summary, live demo link, and CI badge
2. Screenshots of the main screens (from Phase 2)
3. Core workflow diagram (Mermaid renders on GitHub)
4. Features by role and phase
5. Architecture overview and key decisions, linking to ADRs
6. Tech stack
7. Running locally and running the tests
8. Demo credentials and a guided tour
9. Link to the API documentation
10. Known limitations (free-tier cold starts) and future work
11. Who built what: the parts you wrote and the parts Claude Code wrote

### Architecture Decision Records (`docs/adr/`)

One page each: context, decision, alternatives considered, and consequences.

| ADR | Decision | Written in |
|---|---|---|
| 0001 | Modular monolith instead of microservices | Phase 1 |
| 0002 | Synchronous SQLAlchemy instead of async | Phase 1 |
| 0003 | Roles and permissions defined in code instead of in the database | Phase 1 |
| 0004 | Short-lived JWT access tokens, rotating refresh tokens in an `HttpOnly` cookie, and in-memory rate limiting | Phase 1 |
| 0005 | Fixed 30-minute slots enforced by partial unique indexes | Phase 1 |
| 0006 | Stock batches, a movement ledger, and FEFO allocation | Phase 1 |
| 0007 | A branch-aware schema from Phase 1 | Phase 1 |
| 0008 | Render and Neon hosting, with migrations at container start | Phase 1 |
| 0009 | Public API docs in production as a portfolio exception | Phase 1 |
| 0010 | The React app served by the API from the same origin | Phase 2 |
| 0011 | An API client generated from the OpenAPI schema | Phase 2 |
| 0012 | Separate `/portal` endpoints for patients | Phase 4 |
| 0013 | Managers administer staff accounts except Admin and Manager | Phase 5 |

### Code documentation

Claude Code writes the documentation, and you review it. Docstrings are detailed, and import comments are one line.

- **Docstrings:** every module, package `__init__.py`, class, and function, including private helpers, gets a Google-style docstring. It has a one-line summary; a paragraph on what the code does, the business rules it enforces, and why it works this way; and `Args`, `Returns`, and `Raises` sections, plus `Attributes` for classes. Add an `Example` section when usage isn't obvious.
- **Test docstrings:** each test describes the scenario and the expected result.
- **Import comments:** import one name per line, with a one-line comment above it saying what the library or function is and how the file uses it.
- **Other comments** explain *why* (a business rule or a trade-off), never *what* the code does.
- **React code** follows the same rules with TSDoc comments. Generated API client files and copied shadcn/ui components are skipped.
- **Your files:** Claude Code can't edit `config.py` or migrations, so it tells you which docstrings and comments to add there.
- OpenAPI summaries, descriptions, and examples are documentation too, and are reviewed like code.

Ruff enforces part of this through `backend/pyproject.toml`, both locally and in CI:

```toml
[tool.ruff.lint]
extend-select = ["D", "I"]  # D: docstrings, I: import sorting

[tool.ruff.lint.pydocstyle]
convention = "google"

[tool.ruff.lint.isort]
force-single-line = true  # one imported name per line

[tool.ruff.lint.per-file-ignores]
"migrations/**" = ["D"]
"tests/**" = ["D100", "D104"]
```

Ruff fails when a public module, class, or function has no docstring, or when a docstring leaves out an argument. It can't check private helpers, how detailed a docstring is, or whether each import has its comment, so Claude Code checks those before you commit. Always write one name per import: when Ruff splits a combined import onto separate lines, the comment stays with the first name only.

Example, from `backend/app/modules/pharmacy/allocation.py`:

```python
"""Stock allocation rules for dispensing and stock transfers.

These functions never touch the database. Services lock the batch rows,
call these functions to decide which batches to use, and then save the
result in the same transaction.
"""

# Immutable record type for allocation results.
from dataclasses import dataclass

# Error that the API turns into a 409 Conflict response.
from app.core.errors import ConflictError


@dataclass(frozen=True)
class Allocation:
    """Units taken from one stock batch.

    Attributes:
        batch_id: Identifier of the batch the units come from.
        quantity: Units taken from that batch, always greater than zero.
    """

    batch_id: str
    quantity: int


def allocate_fefo(batches: list[tuple[str, int]], quantity: int) -> list[Allocation]:
    """Allocate a quantity from stock batches, earliest expiry first.

    FEFO (first expired, first out) takes stock from the batches that expire
    soonest, so less medicine goes to waste. The caller passes only usable
    batches, already sorted; this function decides how many units to take
    from each one.

    Args:
        batches: ``(batch_id, units_on_hand)`` pairs for one medicine, sorted
            by expiry date with the earliest first. Expired batches must
            already be excluded.
        quantity: Units to allocate. Must be greater than zero.

    Returns:
        One allocation per batch used, in the order stock was taken. The
        allocated quantities add up to ``quantity``.

    Raises:
        ConflictError: If the batches hold fewer units than ``quantity``.
            Nothing is allocated in that case.
    """
    allocations: list[Allocation] = []
    remaining = quantity
    for batch_id, on_hand in batches:
        if remaining == 0:
            break
        taken = min(on_hand, remaining)
        allocations.append(Allocation(batch_id, taken))
        remaining -= taken
    if remaining > 0:
        raise ConflictError("Not enough stock to allocate the full quantity.")
    return allocations
```

---

## 18. Roadmap

There are no dates. Finish, deploy, and tag each milestone before starting the next one.

### Rough size

These are estimates for planning at 5–8 hours a day, not deadlines.

| Phase | Rough size |
|---|---|
| 1. Core hospital API | 5–7 weeks |
| 2. Staff web app | 3–4 weeks |
| 3. Pharmacy branches | 2–3 weeks |
| 4. Patient portal | 2–3 weeks |
| 5. Customer service and management | 2–3 weeks |

The whole plan is roughly 14–20 weeks. Phase 1 on its own is already a strong portfolio project, so you can start applying for jobs once `v1.0.0` is live and keep building afterward.

### Weekly rhythm

- **Start of the week:** move the week's issues to Ready, and keep only one milestone in progress.
- **Every day:** end with passing tests and a pushed branch.
- **End of the week:** review the board, write any ADRs that are due, update this plan if a decision changed, and take a lighter day.

### Phase 1: Core hospital API

**Milestone 1.1: Foundation**

- Repository, project board, and issues; commit `CLAUDE.md` and `.claude/settings.json`
- uv project, FastAPI app factory, Ruff with the docstring and import rules (§17), and pre-commit
- Docker Compose with PostgreSQL
- Settings from `.env` (you)
- Database session, base mixins, and Alembic setup (you)
- Health endpoints, error format, and request-ID logging
- Test infrastructure and the first CI workflow

**Milestone 1.2: Identity and access → `v0.1.0`, a deployed walking skeleton**

- Users table, password hashing, and the `create-admin` command
- Login, cookie refresh with rotation, logout, `/auth/me`, change password, and forced password change
- Login rate limiting
- Permissions module, `require_permission`, and the route guard test
- Staff administration endpoints
- Production Dockerfile and first deployment (§16)

**Milestone 1.3: Organization, audit, and patients → `v0.2.0`**

- Departments, the default branch, staff profiles, and the doctors directory
- Audit module and audit search
- Patients: register with MRN, get, update, and paginated search

**Milestone 1.4: Scheduling → `v0.3.0`**

- Appointments with partial unique indexes, booking, and conflict handling
- Available slots, list and filters, and the doctor's own schedule
- Cancel, no-show, and check-in (which creates the visit)

**Milestone 1.5: Clinical and prescriptions → `v0.4.0`**

- Vitals; visit notes, diagnosis, and completion
- Care-relationship rule and patient history
- Prescriptions: issue, cancel, and the pharmacist queue

**Milestone 1.6: Pharmacy → `v0.5.0`**

- Medicine catalog, receiving batches, and the movement ledger
- `allocate_fefo` and dispensing from the pharmacist's branch
- Stock adjustments, and low-stock and expiring reports

**Milestone 1.7: Release readiness → `v1.0.0`**

- Workflow test (pytest) that runs the core flow through the API across all Phase 1 roles
- `seed-demo` with `--reset`, and demo-account protection
- Security checklist (§12), OpenAPI polish, README, and ADRs 0001–0009
- Fresh-eyes test: clone the repository into an empty folder and follow only the README

### Phase 2: Staff web app → `v1.1.0`

- **2.1 Frontend foundation:** Vite, TypeScript, Tailwind, and shadcn/ui; OpenAPI export, generated client, and the contract check in CI; session handling (login, restore after reload, refresh on `401`, forced password change); app shell with role-based navigation; same-origin serving in Docker
- **2.2** Admin and reception screens
- **2.3** Nurse and doctor screens
- **2.4** Pharmacy screens
- **2.5** Playwright core-workflow test, accessibility pass, README screenshots, and ADRs 0010–0011

### Phase 3: Pharmacy branches → `v1.2.0`

- **3.1** Branch administration and pharmacist assignment
- **3.2** Branch-scoped stock, dispensing, and reports; availability across branches
- **3.3** Stock transfers: request, dispatch, receive, and cancel
- **3.4** Branch and transfer screens, and the transfer end-to-end test

### Phase 4: Patient portal → `v1.3.0`

- **4.1** Portal activation codes and account activation
- **4.2** Portal endpoints for profile, appointments, visits, and prescriptions
- **4.3** Self-booking and cancellation rules
- **4.4** Portal screens, the portal end-to-end test, and ADR 0012

### Phase 5: Customer service and management → `v1.4.0`

- **5.1** Tickets backend and state rules
- **5.2** Portal tickets and the support inbox screens
- **5.3** Manager role and delegated staff administration, with ADR 0013
- **5.4** Report endpoints and the management dashboard
- **5.5** Final hardening, README update, and release

---

## 19. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Never finishing without a deadline | Medium | High | Every milestone ends deployed and tagged; one milestone in progress at a time; Phase 1 is portfolio-ready on its own |
| Scope creep | High | High | Phase boundaries; optional ideas stay in the backlog; `CLAUDE.md` tells Claude Code to flag work from a later phase |
| Backend code you can't explain | Medium | High | You write backend logic and tests; detailed docstrings and import comments explain every file; reviews explain principles; PR descriptions in your own words |
| Frontend work pulls focus from the backend | Medium | Medium | The frontend starts only after `v1.0.0`; Claude Code writes it while you review |
| Security mistakes in cookies, tokens, or access rules | Medium | High | Same-origin design, security checklist, authorization matrix, and isolation and delegated-administration tests |
| Concurrency bugs (double booking, negative stock, transfers) | Medium | High | Database constraints, row locks, and conservation and concurrency tests |
| Free-tier limits or policy changes | Low | Medium | Containerized app, swappable hosting, and documented limits |
| Burnout from long daily sessions | Medium | High | A lighter day every week; stop when the day's goal is met |

---

## Appendix A: Starter files

| File | Location in the repository | Purpose |
|---|---|---|
| `PROJECT_PLAN.md` | `docs/PROJECT_PLAN.md` | This plan |
| `CLAUDE.md` | `CLAUDE.md` | Rules Claude Code loads in every session |
| `settings.json` | `.claude/settings.json` | Blocks Claude Code from your secrets, configuration, and migration files |

Commit these files in Milestone 1.1. Folders whose names start with a dot, such as `.claude`, are hidden by default in macOS and Linux file browsers.

## Appendix B: Glossary

| Term | Meaning |
|---|---|
| ADR | Architecture Decision Record: a one-page explanation of a decision and its trade-offs |
| BOLA | Broken Object Level Authorization: reaching a record you shouldn't by changing its ID; ranked first in the OWASP API Security Top 10 |
| Care relationship | The rule that a doctor may read a patient's clinical data only if they have a non-cancelled appointment with that patient |
| Contract check | A CI step that regenerates the web client from the API's OpenAPI schema and fails if anything changed |
| CSP | Content-Security-Policy: a response header that limits where a page may load scripts and other resources from |
| CSRF | Cross-Site Request Forgery: another website making your browser send a request with your cookies |
| E2E test | End-to-end test: drives the real app in a browser, the way a user would |
| FEFO | First Expired, First Out: dispense from the batch that expires soonest |
| IANA timezone | A standard timezone name such as `Europe/London` |
| MRN | Medical Record Number: the hospital's unique patient identifier |
| OpenAPI | A standard, machine-readable description of an API; FastAPI generates it automatically |
| Partial unique index | A unique index that applies only to rows matching a condition |
| Row lock | `SELECT … FOR UPDATE`: other transactions must wait before changing the locked rows |
| SameSite cookie | A cookie setting that controls whether browsers send the cookie with requests from other sites |
| SPA | Single-page application: a web app that loads once and then updates the page with JavaScript |
| Walking skeleton | The thinnest end-to-end version of a system, deployed early and grown feature by feature |
