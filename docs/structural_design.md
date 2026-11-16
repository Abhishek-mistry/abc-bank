# STRUCTURAL DESIGN — ABC Bank (Toy Banking System)

| Field | Value |
|---|---|
| Document version | **v1.0** (FROZEN) |
| Author | 00llm (CEO / Lead Architect) |
| Date | 2026-09-28 |
| Audience | 01llm – 09llm |
| Purpose | Single source of truth. Every table, column, endpoint, JSON key, error code and function name used by any agent MUST appear in this document. |

---

## 0. Rules of Engagement

1. **This document is law.** If code and document disagree, the code is wrong.
2. **No guessing, no inventing.** If something is missing or ambiguous, send `xxto00.md` titled `CHANGE REQUEST`. Do not improvise names, fields or endpoints.
3. **Only 00llm edits this file.** Amendments are announced in `memotoall.md` with a version bump (v1.1, v1.2 …).
4. **Ownership is strict** (see §3.3). Never edit a file you don't own; DM the owner (`xxtoyy.md`).
5. **Security is intentionally minimal** (university DBMS project). No JWT, no rate-limiting, no HTTPS, no CSRF. Passwords are hashed with `werkzeug.security` only because it is one line. The focus is **ACID transactions, ledger correctness and realistic banking logic.**

---

## 1. Scope

**In scope**
- Account management (register, login, profile, multiple accounts, freeze/close)
- Money: deposit, transfer (send/receive), history, reversal
- Robust failure handling: simulated network failures, disconnects, rollback, idempotent retries, missing data
- Personal loans only: apply → personal details → income docs (PAN/Aadhar) → guarantor → approval (rate decided) → disbursement → repayment schedule (6–36 months) → repayments → closure
- Notifications, dashboard, system health, ledger integrity checks

**Out of scope:** other loan types (shown greyed-out in UI only), cards, KYC verification, real auth, admin portal, interest on savings, withdrawals.

---

## 2. Tech Stack & Shared Constants

| Item | Value |
|---|---|
| Backend | Python 3.10+, Flask 3.x |
| Database | MySQL **8.0.16+** (InnoDB; CHECK constraints must be enforced) |
| DB driver | `mysql-connector-python` (with connection pooling) |
| Frontend | Plain HTML + CSS + vanilla JS (no frameworks, no build step) |
| Tests | `pytest`, `requests` |
| DB name / user / pass | `abc_bank` / `abc_user` / `abc_pass` |
| DB host / port | `127.0.0.1` / `3306` |
| Server | `http://127.0.0.1:5000` — Flask serves API under `/api` **and** the `frontend/` folder at `/` |
| Env vars | `DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, FLASK_PORT (5000), DEBUG_TOOLS (default 1), UPLOAD_DIR (default backend/uploads)` |
| Currency | INR, symbol `₹` |
| Timezone | **UTC everywhere.** DB session `time_zone='+00:00'` |
| Bank name | `ABC Bank` |
| System user | `user_id=1`, username `__bank__` (cannot log in) |
| System account | `account_id=1`, `account_number="000000000001"`, `is_system=1` (counter-party for deposits, loan disbursements, repayments; may go negative) |

**One-time DB bootstrap (README, done by human):**
```sql
CREATE DATABASE abc_bank CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'abc_user'@'localhost' IDENTIFIED BY 'abc_pass';
GRANT ALL PRIVILEGES ON abc_bank.* TO 'abc_user'@'localhost';
```
Then: `python backend/init_db.py` (creates schema + seed) and `python backend/app.py`.

---

## 3. Architecture

### 3.1 Flow (from the wireframe)

```
 ┌────────────┐   fetch /api/*     ┌──────────────────────────┐     SQL      ┌──────────────┐
 │  Front-end │ ─────────────────► │        Back-end          │ ───────────► │    MySQL     │
 │ (A → B UI) │ ◄───────────────── │  Flask blueprints        │ ◄─────────── │   abc_bank   │
 └────────────┘   JSON envelope    │  ┌────────┐ ┌──────────┐ │              │ ledger, txns │
                                   │  │  Auth  │ │ Banking  │ │              │ loans, ...   │
                                   │  │(X-User)│ │ (ledger) │ │              └──────────────┘
                                   │  └────────┘ └──────────┘ │
                                   │  ┌────────┐ ┌──────────┐ │
                                   │  │ Loans  │ │ Notifier │ │
                                   │  └────────┘ └──────────┘ │
                                   └──────────────────────────┘
```
Money always flows: **Front-end → transaction/loan route → service → `ledger.move_money` → DB (single ACID transaction)**.

### 3.2 Repository layout

```
abc-bank/
├── backend/
│   ├── app.py  config.py  db.py  errors.py  responses.py  money.py  utils.py  middleware.py
│   ├── init_db.py  schema.sql  requirements.txt  README.md
│   ├── routes/
│   │   ├── auth_routes.py  user_routes.py  account_routes.py  transaction_routes.py
│   │   ├── loan_routes.py  notification_routes.py  dashboard_routes.py  system_routes.py
│   ├── services/
│   │   ├── ledger.py  failure_sim.py  transfer_service.py
│   │   ├── loan_engine.py  loan_service.py
│   │   ├── notify.py  health_service.py
│   ├── uploads/            (runtime, git-ignored)
│   └── tests/              (08llm)
├── frontend/
│   ├── index.html  dashboard.html  send-money.html  deposit.html  transactions.html
│   ├── loans.html  take-loan.html  profile.html  notifications.html
│   ├── css/  style.css  transactions.css  loans.css
│   └── js/   api.js  common.js  auth.js  dashboard.js  profile.js  notifications.js
│             send-money.js  deposit.js  transactions.js  loans.js  take-loan.js
├── tools/   check_schema.py  check_frontend_contract.py   (09llm)
├── docs/    (09llm)
└── README.md                                               (09llm)
```

### 3.3 File ownership

| Agent | Owns |
|---|---|
| **01llm** | `config.py db.py errors.py responses.py money.py utils.py middleware.py init_db.py schema.sql app.py requirements.txt backend/README.md services/notify.py backend/selfcheck_db.py` |
| **02llm** | `services/ledger.py services/failure_sim.py services/transfer_service.py routes/transaction_routes.py backend/selfcheck_txn.py` |
| **03llm** | `services/loan_engine.py services/loan_service.py routes/loan_routes.py backend/selfcheck_loans.py` |
| **04llm** | `routes/auth_routes.py user_routes.py account_routes.py notification_routes.py dashboard_routes.py system_routes.py services/health_service.py backend/selfcheck_api.py` |
| **05llm** | `frontend/index.html dashboard.html profile.html notifications.html css/style.css js/api.js js/common.js js/auth.js js/dashboard.js js/profile.js js/notifications.js` |
| **06llm** | `frontend/send-money.html deposit.html transactions.html css/transactions.css js/send-money.js js/deposit.js js/transactions.js` |
| **07llm** | `frontend/loans.html take-loan.html css/loans.css js/loans.js js/take-loan.js` |
| **08llm** | `backend/tests/**  pytest.ini` |
| **09llm** | `tools/** docs/** README.md` |

### 3.4 Blueprints (exact names — `app.py` auto-registers these)

| Module | Blueprint variable | `url_prefix` |
|---|---|---|
| `routes/auth_routes.py` | `auth_bp` | `/api/auth` |
| `routes/user_routes.py` | `user_bp` | `/api/users` |
| `routes/account_routes.py` | `account_bp` | `/api/accounts` |
| `routes/transaction_routes.py` | `txn_bp` | `/api/transactions` |
| `routes/loan_routes.py` | `loan_bp` | `/api/loans` |
| `routes/notification_routes.py` | `notif_bp` | `/api/notifications` |
| `routes/dashboard_routes.py` | `dash_bp` | `/api/dashboard` |
| `routes/system_routes.py` | `system_bp` | `/api/system` |

---

## 4. Database Schema (authoritative DDL → `backend/schema.sql`)

Rules: InnoDB, `utf8mb4`, all money `DECIMAL(15,2)`, all timestamps UTC. Format validation (PAN, Aadhar, phone…) lives in the API layer, not in CHECKs. `schema.sql` starts with `SET FOREIGN_KEY_CHECKS=0; DROP TABLE IF EXISTS …(all 10)…; SET FOREIGN_KEY_CHECKS=1;` so it is re-runnable.

```sql
CREATE TABLE users (
  user_id        INT UNSIGNED NOT NULL AUTO_INCREMENT,
  username       VARCHAR(50)  NOT NULL,
  password_hash  VARCHAR(255) NOT NULL,
  full_name      VARCHAR(100) NOT NULL,
  email          VARCHAR(120) NOT NULL,
  phone          VARCHAR(15)  NOT NULL,
  address        VARCHAR(255) NULL,
  date_of_birth  DATE NULL,
  is_system      TINYINT(1)   NOT NULL DEFAULT 0,
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id),
  UNIQUE KEY uq_users_username (username),
  UNIQUE KEY uq_users_email (email)
) ENGINE=InnoDB;

CREATE TABLE accounts (
  account_id      INT UNSIGNED NOT NULL AUTO_INCREMENT,
  account_number  CHAR(12) NOT NULL,
  user_id         INT UNSIGNED NOT NULL,
  account_type    ENUM('SAVINGS','CURRENT') NOT NULL DEFAULT 'SAVINGS',
  balance         DECIMAL(15,2) NOT NULL DEFAULT 0.00,
  status          ENUM('ACTIVE','FROZEN','CLOSED') NOT NULL DEFAULT 'ACTIVE',
  is_system       TINYINT(1) NOT NULL DEFAULT 0,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (account_id),
  UNIQUE KEY uq_accounts_number (account_number),
  KEY idx_accounts_user (user_id),
  CONSTRAINT fk_accounts_user FOREIGN KEY (user_id) REFERENCES users(user_id),
  CONSTRAINT chk_accounts_balance CHECK (is_system = 1 OR balance >= 0)
) ENGINE=InnoDB;

CREATE TABLE loans (
  loan_id           INT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id           INT UNSIGNED NOT NULL,
  account_id        INT UNSIGNED NOT NULL,           -- disbursement + default repayment account
  loan_type         ENUM('PERSONAL') NOT NULL DEFAULT 'PERSONAL',
  status            ENUM('DRAFT','PENDING_REVIEW','APPROVED','REJECTED','ACTIVE','CLOSED','CANCELLED') NOT NULL DEFAULT 'DRAFT',
  applicant_name    VARCHAR(100) NULL,
  applicant_phone   VARCHAR(15)  NULL,
  applicant_address VARCHAR(255) NULL,
  applicant_dob     DATE NULL,
  requested_amount  DECIMAL(15,2) NULL,
  tenure_months     TINYINT UNSIGNED NULL,
  pan_number        CHAR(10) NULL,
  aadhar_number     CHAR(12) NULL,
  employment_type   ENUM('SALARIED','SELF_EMPLOYED','BUSINESS','OTHER') NULL,
  monthly_income    DECIMAL(15,2) NULL,
  approved_amount   DECIMAL(15,2) NULL,
  interest_rate     DECIMAL(5,2)  NULL,               -- annual %, e.g. 5.00
  emi_amount        DECIMAL(15,2) NULL,
  total_interest    DECIMAL(15,2) NULL,
  total_payable     DECIMAL(15,2) NULL,
  review_mode       ENUM('AUTO','APPROVE','REJECT') NULL,
  review_remarks    VARCHAR(255) NULL,
  rejection_codes   VARCHAR(255) NULL,                -- comma-separated codes, see §9
  rate_breakdown    JSON NULL,
  submitted_at      DATETIME NULL,
  reviewed_at       DATETIME NULL,
  disbursed_at      DATETIME NULL,
  closed_at         DATETIME NULL,
  created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (loan_id),
  KEY idx_loans_user_status (user_id, status),
  CONSTRAINT fk_loans_user    FOREIGN KEY (user_id)    REFERENCES users(user_id),
  CONSTRAINT fk_loans_account FOREIGN KEY (account_id) REFERENCES accounts(account_id),
  CONSTRAINT chk_loans_amount CHECK (requested_amount IS NULL OR requested_amount BETWEEN 5000 AND 500000),
  CONSTRAINT chk_loans_tenure CHECK (tenure_months IS NULL OR tenure_months IN (6,12,18,24,36))
) ENGINE=InnoDB;

CREATE TABLE loan_documents (
  document_id        INT UNSIGNED NOT NULL AUTO_INCREMENT,
  loan_id            INT UNSIGNED NOT NULL,
  document_type      ENUM('INCOME_PROOF','PAN_CARD','AADHAR_CARD') NOT NULL,
  original_filename  VARCHAR(255) NOT NULL,
  stored_path        VARCHAR(255) NOT NULL,
  mime_type          VARCHAR(50)  NOT NULL,
  size_bytes         INT UNSIGNED NOT NULL,
  uploaded_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (document_id),
  UNIQUE KEY uq_loan_doc_type (loan_id, document_type),
  CONSTRAINT fk_docs_loan FOREIGN KEY (loan_id) REFERENCES loans(loan_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE guarantors (
  guarantor_id     INT UNSIGNED NOT NULL AUTO_INCREMENT,
  loan_id          INT UNSIGNED NOT NULL,
  guarantor_name   VARCHAR(100) NOT NULL,
  guarantor_aadhar CHAR(12) NOT NULL,
  guarantor_phone  VARCHAR(15) NULL,
  relationship     ENUM('SPOUSE','PARENT','SIBLING','CHILD','OTHER_RELATIVE','FRIEND','COLLEAGUE') NOT NULL,
  created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (guarantor_id),
  UNIQUE KEY uq_guarantor_loan (loan_id),              -- exactly one guarantor per loan
  CONSTRAINT fk_guarantor_loan FOREIGN KEY (loan_id) REFERENCES loans(loan_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE transactions (
  txn_id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  txn_ref          CHAR(36) NOT NULL,                  -- UUID v4, public identifier
  idempotency_key  VARCHAR(64) NULL,                   -- NULL on FAILED rows (see §8)
  txn_type         ENUM('TRANSFER','DEPOSIT','LOAN_DISBURSEMENT','LOAN_REPAYMENT','REVERSAL') NOT NULL,
  from_account_id  INT UNSIGNED NULL,
  to_account_id    INT UNSIGNED NULL,
  amount           DECIMAL(15,2) NOT NULL,
  status           ENUM('PENDING','COMPLETED','FAILED','REVERSED') NOT NULL DEFAULT 'PENDING',
  failure_code     VARCHAR(40)  NULL,
  failure_reason   VARCHAR(255) NULL,
  description      VARCHAR(255) NULL,
  related_txn_id   BIGINT UNSIGNED NULL,               -- REVERSAL → original
  loan_id          INT UNSIGNED NULL,
  initiated_by     INT UNSIGNED NULL,
  created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at     DATETIME NULL,
  PRIMARY KEY (txn_id),
  UNIQUE KEY uq_txn_ref (txn_ref),
  UNIQUE KEY uq_txn_idem (idempotency_key),
  KEY idx_txn_from (from_account_id, txn_id),
  KEY idx_txn_to   (to_account_id, txn_id),
  KEY idx_txn_loan (loan_id),
  CONSTRAINT fk_txn_from    FOREIGN KEY (from_account_id) REFERENCES accounts(account_id),
  CONSTRAINT fk_txn_to      FOREIGN KEY (to_account_id)   REFERENCES accounts(account_id),
  CONSTRAINT fk_txn_related FOREIGN KEY (related_txn_id)  REFERENCES transactions(txn_id),
  CONSTRAINT fk_txn_loan    FOREIGN KEY (loan_id)         REFERENCES loans(loan_id),
  CONSTRAINT fk_txn_user    FOREIGN KEY (initiated_by)    REFERENCES users(user_id),
  CONSTRAINT chk_txn_amount CHECK (amount > 0)
) ENGINE=InnoDB;

CREATE TABLE ledger_entries (
  entry_id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  txn_id         BIGINT UNSIGNED NOT NULL,
  account_id     INT UNSIGNED NOT NULL,
  entry_type     ENUM('DEBIT','CREDIT') NOT NULL,
  amount         DECIMAL(15,2) NOT NULL,
  balance_after  DECIMAL(15,2) NOT NULL,
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (entry_id),
  KEY idx_ledger_account (account_id, entry_id),
  KEY idx_ledger_txn (txn_id),
  CONSTRAINT fk_ledger_txn     FOREIGN KEY (txn_id)     REFERENCES transactions(txn_id),
  CONSTRAINT fk_ledger_account FOREIGN KEY (account_id) REFERENCES accounts(account_id),
  CONSTRAINT chk_ledger_amount CHECK (amount > 0)
) ENGINE=InnoDB;

CREATE TABLE repayment_schedule (
  installment_id      INT UNSIGNED NOT NULL AUTO_INCREMENT,
  loan_id             INT UNSIGNED NOT NULL,
  installment_no      TINYINT UNSIGNED NOT NULL,
  due_date            DATE NOT NULL,
  emi_amount          DECIMAL(15,2) NOT NULL,
  principal_component DECIMAL(15,2) NOT NULL,
  interest_component  DECIMAL(15,2) NOT NULL,
  balance_after       DECIMAL(15,2) NOT NULL,
  status              ENUM('PENDING','PAID') NOT NULL DEFAULT 'PENDING',
  paid_at             DATETIME NULL,
  paid_txn_id         BIGINT UNSIGNED NULL,
  PRIMARY KEY (installment_id),
  UNIQUE KEY uq_schedule (loan_id, installment_no),
  CONSTRAINT fk_sched_loan FOREIGN KEY (loan_id)     REFERENCES loans(loan_id) ON DELETE CASCADE,
  CONSTRAINT fk_sched_txn  FOREIGN KEY (paid_txn_id) REFERENCES transactions(txn_id)
) ENGINE=InnoDB;

CREATE TABLE notifications (
  notification_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id         INT UNSIGNED NOT NULL,
  type            VARCHAR(30)  NOT NULL,
  title           VARCHAR(100) NOT NULL,
  message         VARCHAR(255) NOT NULL,
  related_ref     VARCHAR(40)  NULL,                  -- txn_ref or loan_id (as text)
  is_read         TINYINT(1) NOT NULL DEFAULT 0,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (notification_id),
  KEY idx_notif_user (user_id, is_read, notification_id),
  CONSTRAINT fk_notif_user FOREIGN KEY (user_id) REFERENCES users(user_id)
) ENGINE=InnoDB;

CREATE TABLE system_settings (
  setting_key   VARCHAR(50)  NOT NULL,
  setting_value VARCHAR(255) NOT NULL,
  updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (setting_key)
) ENGINE=InnoDB;
-- seeded keys: sim_mode='NONE', sim_probability='0.30'
```

### 4.1 Ledger invariants (checked by `GET /api/system/integrity` and by QA)

| ID | Invariant |
|---|---|
| **I1** | For every transaction with status `COMPLETED` or `REVERSED`: `SUM(DEBIT) = SUM(CREDIT)` and both `> 0` in `ledger_entries`. |
| **I2** | For every account: `accounts.balance = SUM(CREDIT) − SUM(DEBIT)` over its ledger entries. |
| **I3** | Transactions with status `FAILED` or `PENDING` have **zero** ledger entries. No `PENDING` row may exist once a request has finished. |
| **I4** | `SUM(accounts.balance)` over **all** accounts (system included) `= 0.00`. |
| **I5** | No non-system account has `balance < 0`. |
| **I6** | Every `ACTIVE` loan has `tenure_months` schedule rows, `SUM(principal_component) = approved_amount`. Every `CLOSED` loan has all rows `PAID`. |

---

## 5. Global API Conventions

**5.1 Base & format.** All endpoints under `/api`, JSON in/out (UTF-8), `Content-Type: application/json` (exception: document upload = `multipart/form-data`).

**5.2 Envelope (always).**
```json
{ "success": true,  "data": { ... } }
{ "success": false, "error": { "code": "INSUFFICIENT_FUNDS", "message": "Human readable text", "details": { } } }
```
`details` is always an object (may be `{}`). Validation errors use `details.fields = {"field_name": "reason"}`.

**5.3 Auth (toy).** After login the client sends header `X-User-Id: <int>` on every request marked "Auth = yes" in Appendix A. Missing/unknown user → `401 AUTH_REQUIRED`. Accessing another user's resource → `403 FORBIDDEN`.

**5.4 Money.** In **responses**, every money value is a **string with exactly 2 decimals** (`"10000.00"`). In **requests**, backend accepts a JSON number or numeric string with ≤ 2 decimals; frontend always sends strings. Backend uses `decimal.Decimal` exclusively — **never `float`**. Rounding: `ROUND_HALF_UP`.

**5.5 Dates.** Timestamps: `"2026-09-28T10:15:30Z"` (UTC, seconds precision). Dates: `"YYYY-MM-DD"`.

**5.6 Pagination.** Query `page` (1-based, default 1), `page_size` (default 10, max 50). Paginated `data`:
```json
{ "items": [ ... ], "page": 1, "page_size": 10, "total_items": 23, "total_pages": 3 }
```

**5.7 Field validation rules.**

| Field | Rule |
|---|---|
| `username` | 3–30 chars, `[A-Za-z0-9_]` |
| `password` | ≥ 4 chars |
| `email` | contains `@` and a `.` after it, ≤ 120 |
| `phone` | 10–15 digits |
| `account_number` | exactly 12 digits |
| `pan_number` | `^[A-Z]{5}[0-9]{4}[A-Z]$` |
| `aadhar_number`, `guarantor_aadhar` | exactly 12 digits |
| `note` / `description` | ≤ 100 chars |
| `idempotency_key` | 8–64 chars, `[A-Za-z0-9_-]` |
| Money limits | transfer 1.00 – 200,000.00 · deposit 1.00 – 100,000.00 · loan 5,000.00 – 500,000.00 |

---

## 6. Shared Object Shapes

**User**
```json
{ "user_id": 2, "username": "alice", "full_name": "Alice Sharma", "email": "alice@abcbank.test",
  "phone": "9876500001", "address": "12 MG Road, Pune", "date_of_birth": "1995-04-12", "created_at": "2026-09-28T09:00:00Z" }
```

**Account**
```json
{ "account_id": 2, "account_number": "100000000001", "account_type": "SAVINGS",
  "balance": "10000.00", "status": "ACTIVE", "created_at": "2026-09-28T09:00:00Z" }
```

**Transaction** (`direction` is `"OUT"` if the *requesting user's* account is the sender, else `"IN"`; when `account_id` filter is used it is relative to that account; `null` if no viewer). System account name is `"ABC Bank"`; other names are masked via `mask_name` (e.g. `"Bob S."`).
```json
{ "txn_ref": "3f2b8c1e-5a4d-4c8e-9b1a-0d2f6e7a1c33", "txn_type": "TRANSFER", "status": "COMPLETED",
  "amount": "1000.00", "from_account_number": "100000000001", "from_name": "Alice S.",
  "to_account_number": "100000000002", "to_name": "Bob S.", "description": "Rent share",
  "direction": "OUT", "failure_code": null, "failure_reason": null, "related_txn_ref": null,
  "loan_id": null, "created_at": "2026-09-28T10:15:30Z", "completed_at": "2026-09-28T10:15:30Z" }
```

**Installment**
```json
{ "installment_no": 1, "due_date": "2026-10-28", "emi_amount": "4372.57", "principal_component": "3997.57",
  "interest_component": "375.00", "balance_after": "46002.43", "status": "PENDING", "is_overdue": false, "paid_at": null }
```
`is_overdue` = `status=="PENDING" and due_date < today(UTC)` (computed on read, never stored).

**Loan**
```json
{ "loan_id": 7, "loan_type": "PERSONAL", "status": "PENDING_REVIEW", "current_step": 5,
  "account_number": "100000000001",
  "requested_amount": "50000.00", "tenure_months": 12,
  "approved_amount": null, "interest_rate": null, "emi_amount": null, "total_interest": null, "total_payable": null,
  "personal_details": { "full_name": "Alice Sharma", "phone": "9876500001", "address": "12 MG Road, Pune", "date_of_birth": "1995-04-12" },
  "income_details": { "pan_number": "ABCDE1234F", "aadhar_number": "123412341234", "employment_type": "SALARIED", "monthly_income": "60000.00" },
  "documents": [ { "document_type": "PAN_CARD", "original_filename": "pan.png", "uploaded_at": "2026-09-28T10:00:00Z" } ],
  "guarantor": { "guarantor_name": "Ravi Sharma", "guarantor_aadhar": "432143214321", "guarantor_phone": "9876500009", "relationship": "PARENT" },
  "review": { "mode": null, "remarks": null, "rejection_codes": [], "rate_breakdown": null, "reviewed_at": null },
  "installments_paid": 0, "installments_total": 0,
  "submitted_at": "2026-09-28T10:05:00Z", "disbursed_at": null, "closed_at": null, "created_at": "2026-09-28T09:50:00Z" }
```
Rules: sub-objects (`personal_details`, `income_details`, `guarantor`) are `null` until saved. `current_step` is **derived on read** (never stored): `2` until details saved · `3` until income details saved **and** all 3 documents uploaded · `4` while status is `DRAFT` and everything is filled (ready to submit) · `5` once status ≠ `DRAFT`. `rate_breakdown` (when set) = `{"base":"9.00","income_discount":"2.00","guarantor_discount":"1.00","tenure_discount":"1.00","loyalty_discount":"0.00","final_rate":"5.00"}`. `installments_total` = `tenure_months` once ACTIVE/CLOSED, else `0`.

**Notification**
```json
{ "notification_id": 5, "type": "TRANSFER_RECEIVED", "title": "Money received", "message": "₹1,000.00 received from Alice S.",
  "related_ref": "3f2b8c1e-5a4d-4c8e-9b1a-0d2f6e7a1c33", "is_read": false, "created_at": "2026-09-28T10:15:30Z" }
```
Types (exact strings): `TRANSFER_SENT, TRANSFER_RECEIVED, TRANSFER_FAILED, TRANSFER_REVERSED, DEPOSIT, LOAN_SUBMITTED, LOAN_APPROVED, LOAN_REJECTED, LOAN_DISBURSED, REPAYMENT_PAID, LOAN_CLOSED`.

---

## 7. API Contracts

Notation: **Req** = request body/query · **200/201** = success `data` · **Err** = error codes (see Appendix B).

### 7.1 Auth & Users (04llm)

**POST `/api/auth/register`** — Req: `{ "username","password","full_name","email","phone","address"?, "date_of_birth"? }`
Creates the user **and one `SAVINGS` account with balance `0.00`**. → **201** `{ "user": User, "account": Account }`. Err: `VALIDATION_ERROR`, `USERNAME_TAKEN`, `EMAIL_TAKEN`.

**POST `/api/auth/login`** — Req: `{ "username","password" }` → **200** `{ "user": User, "accounts": [Account] }`. Err: `INVALID_CREDENTIALS` (also for the system user).

**GET `/api/users/me`** → **200** `{ "user": User }`.

**PUT `/api/users/me`** — Req: any of `full_name, email, phone, address, date_of_birth` → **200** `{ "user": User }`. Err: `VALIDATION_ERROR`, `EMAIL_TAKEN`.

### 7.2 Accounts (04llm)

**GET `/api/accounts`** → **200** `{ "accounts": [Account] }` (all statuses, ordered by `account_id`).

**POST `/api/accounts`** — Req: `{ "account_type": "SAVINGS" | "CURRENT" }` → **201** `{ "account": Account }`. Account number = random 12 digits, first digit 1–9, retry on collision (max 5). Err: `LIMIT_EXCEEDED` (max 5 non-closed accounts per user).

**GET `/api/accounts/lookup?account_number=XXXXXXXXXXXX`** → **200** `{ "account_number": "100000000002", "holder_name": "Bob S.", "status": "ACTIVE" }`. Err: `ACCOUNT_NOT_FOUND`, `VALIDATION_ERROR`. (Used by Send Money to verify the recipient. Works for any user's account, never for the system account → `ACCOUNT_NOT_FOUND`.)

**GET `/api/accounts/{account_id}`** → **200** `{ "account": Account }`. Err: `NOT_FOUND`, `FORBIDDEN`.

**PATCH `/api/accounts/{account_id}/status`** — Req: `{ "status": "ACTIVE" | "FROZEN" | "CLOSED" }` → **200** `{ "account": Account }`.
Rules: `CLOSED` is terminal. Closing requires `balance == 0.00`, no loan of that account in `PENDING_REVIEW/APPROVED/ACTIVE`, and it must not be the user's last non-closed account. Violations → `INVALID_STATE` (message explains). Row is locked `FOR UPDATE` during the change.

### 7.3 Transactions (02llm)

**POST `/api/transactions/transfer`**
Req:
```json
{ "from_account_number": "100000000001", "to_account_number": "100000000002", "amount": "1000.00",
  "note": "Rent share", "idempotency_key": "b6d5c8f2-9d3a-4e0b-8c11-1f2a3b4c5d6e", "simulate_failure": "NONE" }
```
`note`, `idempotency_key`, `simulate_failure` optional (`simulate_failure` ∈ `NONE, BEFORE_DEBIT, AFTER_DEBIT, BEFORE_COMMIT, DROP_RESPONSE, RANDOM`; overrides the global mode).
→ **201** (new) or **200** (idempotent replay):
```json
{ "transaction": Transaction, "from_account": { "account_number": "100000000001", "balance": "9000.00" }, "idempotent_replay": false }
```
Err: `VALIDATION_ERROR, AUTH_REQUIRED, FORBIDDEN` (sender account not yours), `ACCOUNT_NOT_FOUND` (sender or recipient), `SAME_ACCOUNT_TRANSFER, ACCOUNT_NOT_ACTIVE, INSUFFICIENT_FUNDS, LIMIT_EXCEEDED, SIMULATED_NETWORK_FAILURE, NETWORK_TIMEOUT, TXN_RETRY_EXHAUSTED`.

**POST `/api/transactions/deposit`** — Req: `{ "account_number","amount","note"?,"idempotency_key"?,"simulate_failure"? }` (account must be yours). → **201/200** `{ "transaction": Transaction, "account": { "account_number","balance" }, "idempotent_replay": bool }`. Err as transfer minus recipient errors.

**GET `/api/transactions`** — Query: `account_id?, type?` (`TRANSFER|DEPOSIT|LOAN_DISBURSEMENT|LOAN_REPAYMENT|REVERSAL`), `status?` (`COMPLETED|FAILED|REVERSED`), `from_date?, to_date?` (`YYYY-MM-DD`, inclusive, UTC), `page?, page_size?`
→ **200** paginated `items: [Transaction]`, newest first (`ORDER BY txn_id DESC`). A transaction is visible to the user if `from_account_id` or `to_account_id` is one of the user's accounts. FAILED rows are included.

**GET `/api/transactions/{txn_ref}`** → **200**
```json
{ "transaction": Transaction, "ledger_entries": [ { "account_number": "100000000001", "entry_type": "DEBIT", "amount": "1000.00", "balance_after": "9000.00" } ] }
```
Err: `NOT_FOUND`, `FORBIDDEN`.

**POST `/api/transactions/{txn_ref}/reverse`** — Req: `{ "idempotency_key"?, "simulate_failure"? }` → **201/200**
```json
{ "transaction": Transaction /* txn_type REVERSAL */, "original": Transaction /* status REVERSED */, "idempotent_replay": false }
```
Err: `NOT_FOUND, FORBIDDEN, TXN_NOT_REVERSIBLE, REVERSAL_FUNDS_UNAVAILABLE, ACCOUNT_NOT_ACTIVE` + failure/simulation codes. Rules in §8.9.

### 7.4 Loans (03llm) — Personal loans only

Flow ↔ UI stepper (`Select Type → Details → Documents → Apply → Approval`):

| Step | UI | Endpoint(s) |
|---|---|---|
| 1 Select Type | choose loan type + disbursement account | `POST /api/loans` |
| 2 Details | personal details + amount + tenure | `PUT /api/loans/{id}/details` |
| 3 Documents | PAN, Aadhar, income, uploads | `PUT …/income-details`, `POST …/documents` (×3) |
| 4 Apply | guarantor + review + submit | `PUT …/guarantor`, `POST …/submit` |
| 5 Approval | status, rate, EMI, schedule | `POST …/review`, `POST …/accept`, `GET …/schedule` |

**GET `/api/loans/config`** → **200**
```json
{ "loan_types": [ {"code":"PERSONAL","label":"Personal","enabled":true},
                  {"code":"PROFESSIONAL","label":"Professional","enabled":false},
                  {"code":"GOLD","label":"Gold","enabled":false},
                  {"code":"CAR","label":"Car","enabled":false},
                  {"code":"HOME","label":"Home","enabled":false} ],
  "min_amount": "5000.00", "max_amount": "500000.00", "tenure_options": [6,12,18,24,36],
  "base_rate": "9.00", "best_rate": "5.00",
  "employment_types": ["SALARIED","SELF_EMPLOYED","BUSINESS","OTHER"],
  "relationships": ["SPOUSE","PARENT","SIBLING","CHILD","OTHER_RELATIVE","FRIEND","COLLEAGUE"],
  "document_types": ["INCOME_PROOF","PAN_CARD","AADHAR_CARD"], "max_upload_bytes": 2097152,
  "allowed_mime_types": ["application/pdf","image/png","image/jpeg"] }
```

**GET `/api/loans/estimate?amount=50000.00&tenure_months=12&rate=9.00`** (`rate` optional, default `9.00`) → **200**
`{ "amount":"50000.00","tenure_months":12,"annual_rate":"9.00","emi_amount":"4372.57","total_interest":"2470.84","total_payable":"52470.84" }` (values from §9.4 algorithm). Err: `VALIDATION_ERROR`.

**POST `/api/loans`** — Req: `{ "loan_type": "PERSONAL", "account_number": "100000000001" }` → **201** `{ "loan": Loan }` (status `DRAFT`, `current_step: 2`). Err: `VALIDATION_ERROR` (any type other than PERSONAL), `ACCOUNT_NOT_FOUND`, `FORBIDDEN`, `ACCOUNT_NOT_ACTIVE`.

**GET `/api/loans?status=`** → **200** `{ "loans": [LoanSummary] }` newest first.
`LoanSummary`: `{ "loan_id","loan_type","status","requested_amount","approved_amount","interest_rate","emi_amount","tenure_months","installments_paid","installments_total","next_due_date","created_at" }` (`next_due_date` = `YYYY-MM-DD` or `null`).

**GET `/api/loans/{loan_id}`** → **200** `{ "loan": Loan }`. Err: `NOT_FOUND`, `FORBIDDEN`.

**PUT `/api/loans/{loan_id}/details`** — Req: `{ "full_name","phone","address","date_of_birth","requested_amount","tenure_months" }` (all required) → **200** `{ "loan": Loan }`. Only while `DRAFT`, else `INVALID_STATE`. Err: `VALIDATION_ERROR` (amount out of range, tenure not in options, applicant under 21 years).

**PUT `/api/loans/{loan_id}/income-details`** — Req: `{ "pan_number","aadhar_number","employment_type","monthly_income" }` → **200** `{ "loan": Loan }`. `DRAFT` only.

**POST `/api/loans/{loan_id}/documents`** — `multipart/form-data`: `document_type` (one of 3), `file` (pdf/png/jpg, ≤ 2 MB). Re-upload of the same type **replaces** the previous. Files stored at `{UPLOAD_DIR}/loan_{loan_id}/{document_type}_{uuid}{ext}`. → **201** `{ "document": { "document_type","original_filename","uploaded_at" }, "loan": Loan }`. `DRAFT` only. Err: `VALIDATION_ERROR` (bad type, too large, wrong mime).

**PUT `/api/loans/{loan_id}/guarantor`** — Req: `{ "guarantor_name","guarantor_aadhar","guarantor_phone"?,"relationship" }` → **200** `{ "loan": Loan }`. Upsert (one per loan). `DRAFT` only.

**POST `/api/loans/{loan_id}/submit`** — no body → **200** `{ "loan": Loan }` with `status: PENDING_REVIEW`, `submitted_at` set, notification `LOAN_SUBMITTED`. Err: `LOAN_INCOMPLETE` with `details.missing = ["details","income_details","documents:PAN_CARD","guarantor", …]`, `INVALID_STATE`.

**POST `/api/loans/{loan_id}/review`** — Req: `{ "decision": "AUTO" | "APPROVE" | "REJECT", "remarks"?: "..." }` (simulates the loan officer; no auth restriction — owner only). Only from `PENDING_REVIEW` else `INVALID_STATE`. → **200** `{ "loan": Loan }` with status `APPROVED` or `REJECTED`, `interest_rate`, `emi_amount`, `total_interest`, `total_payable`, `approved_amount` (approved only), `review{}` filled. Notification `LOAN_APPROVED` / `LOAN_REJECTED`. Logic: §9.3.

**POST `/api/loans/{loan_id}/accept`** — Req: `{ "idempotency_key"? }`. Only from `APPROVED`. Disburses money and creates the schedule **atomically**. → **200** `{ "loan": Loan /* ACTIVE */, "transaction": Transaction /* LOAN_DISBURSEMENT */, "schedule": [Installment] }`. Err: `INVALID_STATE, ACCOUNT_NOT_ACTIVE`, + failure codes.

**POST `/api/loans/{loan_id}/cancel`** — from `DRAFT`, `PENDING_REVIEW`, `APPROVED` → **200** `{ "loan": Loan /* CANCELLED */ }`. Else `INVALID_STATE`.

**GET `/api/loans/{loan_id}/schedule`** → **200**
```json
{ "loan_id": 7, "schedule": [Installment],
  "summary": { "paid_count": 1, "total_count": 12, "outstanding_principal": "42005.86", "total_paid": "4372.57", "total_remaining": "48098.27" } }
```
For loans with no schedule yet: `schedule: []`, counts 0, money `"0.00"`.

**POST `/api/loans/{loan_id}/repay`** — Req: `{ "account_number"?, "idempotency_key"?, "simulate_failure"? }` (defaults to the loan's account; must be the user's). Pays the **lowest-numbered PENDING installment** in full. → **201/200** `{ "installment": Installment, "transaction": Transaction /* LOAN_REPAYMENT */, "loan": Loan, "idempotent_replay": false }`. If it was the last installment → loan `CLOSED`, notification `LOAN_CLOSED`. Err: `INVALID_STATE` (loan not ACTIVE), `INSUFFICIENT_FUNDS, ACCOUNT_NOT_ACTIVE, FORBIDDEN` + failure codes.

### 7.5 Notifications (04llm)

**GET `/api/notifications?unread_only=false&page=1&page_size=10`** → **200** paginated `items: [Notification]` plus extra key `unread_count` (int) inside `data`.
**POST `/api/notifications/{notification_id}/read`** → **200** `{ "notification": Notification }`. Err: `NOT_FOUND`, `FORBIDDEN`.
**POST `/api/notifications/read-all`** → **200** `{ "updated": 3 }`.

### 7.6 Dashboard (04llm)

**GET `/api/dashboard`** → **200**
```json
{ "user": { "user_id": 2, "full_name": "Alice Sharma" },
  "primary_account": { "account_id": 2, "account_number": "100000000001", "balance": "10000.00" },
  "total_balance": "10000.00",
  "recent_transactions": [Transaction],
  "unread_notifications": 2,
  "active_loans": 1,
  "next_installment": { "loan_id": 1, "installment_no": 3, "due_date": "2026-11-28", "emi_amount": "4372.57" },
  "promo": { "headline": "5% ONLY.", "subtext": "Personal Loans with competitive rates." },
  "system_health": { "status": "ALL_GOOD", "db": "UP", "simulation_mode": "NONE", "failed_txns_24h": 0 } }
```
`primary_account` = the user's lowest-`account_id` account with status `ACTIVE` (`null` if none). `total_balance` = sum of the user's non-closed account balances. `recent_transactions` = latest 5. `next_installment` = earliest-due PENDING installment across the user's ACTIVE loans, or `null`.

### 7.7 System (04llm)

| Endpoint | Auth | Behaviour |
|---|---|---|
| **GET `/api/system/health`** | no | **200** `{ "status": "ALL_GOOD"\|"SIMULATION_ACTIVE"\|"DEGRADED", "db": "UP"\|"DOWN", "simulation_mode": "NONE", "failed_txns_24h": 0, "server_time": "2026-09-28T10:00:00Z" }`. `DEGRADED` if DB down or integrity fails; else `SIMULATION_ACTIVE` if mode ≠ `NONE`; else `ALL_GOOD`. |
| **GET `/api/system/integrity`** | no | **200** `{ "ok": true, "checks": { "I1": {"ok":true,"violations":[]}, "I2": {...}, "I3": {...}, "I4": {...}, "I5": {...}, "I6": {...} } }`. `violations` = list of objects describing offenders (ids, expected, actual). |
| **GET `/api/system/simulation`** | no | **200** `{ "mode": "NONE", "probability": "0.30", "modes": ["NONE","BEFORE_DEBIT","AFTER_DEBIT","BEFORE_COMMIT","DROP_RESPONSE","RANDOM"] }` |
| **PUT `/api/system/simulation`** | no* | Req `{ "mode", "probability"? }` (probability 0.00–1.00) → **200** same shape as GET. |
| **POST `/api/system/reset`** | no* | Calls `init_db.reset_database()` → **200** `{ "reset": true }`. |

\* Only when env `DEBUG_TOOLS=1`, otherwise `403 FORBIDDEN`.

---

## 8. Transaction Protocols (ACID rules — mandatory)

**8.1 Single code path.** Every balance change goes through `ledger.move_money(...)`. `UPDATE accounts SET balance` may appear **only** in `services/ledger.py` (and in `init_db.py` seeding). QA greps for violations.

**8.2 Caller owns the DB transaction.** `move_money` never commits or rolls back; it runs inside a transaction opened by `db.run_transaction(fn)`.

**8.3 Locking order (global, prevents deadlocks).** Always acquire locks in this order: **(1)** `loans` row → **(2)** original `transactions` row (reversal only) → **(3)** `accounts` rows in **ascending `account_id`** using a single `SELECT … WHERE account_id IN (a,b) ORDER BY account_id FOR UPDATE`. Never read-modify-write a balance in Python without holding the lock.

**8.4 Isolation.** Connections use `READ COMMITTED`. Balance changes are `UPDATE accounts SET balance = balance ± %s WHERE account_id = %s` after the `FOR UPDATE` lock. The `chk_accounts_balance` CHECK is a last-resort backstop; the service must validate funds first.

**8.5 `move_money` order of operations**
1. Lock both accounts (§8.3). 2. Validate: both exist; both `ACTIVE`; `from != to`; unless `from` is the system account, `balance >= amount` (else `INSUFFICIENT_FUNDS` with `details {"available","required"}`).
3. `INSERT transactions` (`status='PENDING'`, new `txn_ref`, `idempotency_key`, `initiated_by`, …).
4. **Hook `BEFORE_DEBIT`.**
5. Debit `from`, read the new balance, `INSERT ledger_entries` (`DEBIT`, `balance_after`).
6. **Hook `AFTER_DEBIT`** (money already deducted inside the open transaction — rollback must restore it).
7. Credit `to`, `INSERT ledger_entries` (`CREDIT`).
8. `UPDATE transactions SET status='COMPLETED', completed_at=UTC_TIMESTAMP()`.
9. **Hook `BEFORE_COMMIT`.** 10. Return `{ "txn_id", "txn_ref", "from_balance_after", "to_balance_after" }`.
Caller then writes notifications (same DB transaction) and returns; `run_transaction` commits. After a successful commit the caller invokes **Hook `DROP_RESPONSE`**.

**8.6 Failure handling.** Any exception in the transaction ⇒ **full ROLLBACK** (balances, ledger, PENDING txn row, notifications all vanish). Then, *outside* the rolled-back transaction, the service calls `ledger.record_failed_txn(...)`, which uses a **new connection/transaction** to insert a `FAILED` transaction row (`failure_code` = error code, `failure_reason` = message, **`idempotency_key = NULL`**, no ledger entries) plus a `TRANSFER_FAILED` notification to the sender (transfers only). `record_failed_txn` never raises; if it fails it logs to stderr.
A `FAILED` row is written for every failure **except**: `VALIDATION_ERROR`, `AUTH_REQUIRED`, `FORBIDDEN`, sender-account-not-found, and `NETWORK_TIMEOUT` (commit already happened). A missing *recipient* IS recorded (`to_account_id = NULL`, `failure_code = ACCOUNT_NOT_FOUND`).

**8.7 Deadlocks / lock timeouts.** `db.run_transaction(fn, retries=3)` retries the **whole** `fn` on MySQL errno **1213** (deadlock) or **1205** (lock wait timeout) with sleeps `0.05s, 0.10s, 0.20s`. Each attempt is a fresh transaction. After the last failure raise `ApiError("TXN_RETRY_EXHAUSTED", ...)` (503).

**8.8 Idempotency.** If `idempotency_key` is supplied:
(a) before locking, look it up; if a `COMPLETED`/`REVERSED` txn exists with that key **and** `initiated_by == user` → return it with `idempotent_replay: true` (HTTP 200) and change nothing;
(b) look it up **again** after acquiring locks (closes the race);
(c) the `uq_txn_idem` unique index is the final backstop — MySQL error **1062** on that index ⇒ roll back, re-read, return replay.
Because `FAILED` rows store no key, a client may safely retry a failed request with the **same key**.

**8.9 Reversal rules** (`POST /api/transactions/{txn_ref}/reverse`)
- Original must be `txn_type='TRANSFER'`, `status='COMPLETED'`, not already reversed, `completed_at` within **24 h**, and the requester must own the **sender** account → else `TXN_NOT_REVERSIBLE` (or `FORBIDDEN` for ownership).
- Lock order §8.3 (original txn row first, then both accounts). Recipient must have `balance >= amount`, else `REVERSAL_FUNDS_UNAVAILABLE` (map `move_money`'s `INSUFFICIENT_FUNDS`).
- Create a `REVERSAL` transaction via `move_money` (`to → from`, same amount, `related_txn_id = original`), set original `status='REVERSED'`, notify both parties (`TRANSFER_REVERSED`). All in one DB transaction.

**8.10 Simulated failures** (`services/failure_sim.py`)

| Mode | Where it fires | Expected outcome |
|---|---|---|
| `NONE` | never | normal |
| `BEFORE_DEBIT` | §8.5 step 4 | raise `SimulatedNetworkError` → rollback → `503 SIMULATED_NETWORK_FAILURE`; balances unchanged; FAILED row recorded |
| `AFTER_DEBIT` | §8.5 step 6 | same, but proves the debit is rolled back |
| `BEFORE_COMMIT` | §8.5 step 9 | same, proves full rollback after credit |
| `DROP_RESPONSE` | after a **successful commit** | raise `SimulatedResponseDropped` → `504 NETWORK_TIMEOUT`; money **did** move; no FAILED row; client retries with same `idempotency_key` and receives `idempotent_replay: true` |
| `RANDOM` | with probability `p` (global `sim_probability`) pick uniformly one of the 4 modes above, else behave as `NONE` | any of the above |

Precedence: per-request `simulate_failure` (if present and ≠ absent) beats the global mode from `system_settings` (`sim_mode`, `sim_probability`). Fixed modes fire with probability 1. `DROP_RESPONSE` error body: `details = {"hint": "Outcome unknown. Retry with the same idempotency_key."}` (no `txn_ref`).

**8.11 Concurrency guarantees (QA verifies).** With N parallel transfers (incl. opposing A→B and B→A): no deadlock surfaces to the client (retries handle it), no negative balances, final balances equal the serial result, I1–I6 hold.

**8.12 Notifications** are inserted through `services/notify.create_notification(cur, ...)` **inside** the same DB transaction as the event (so they roll back with it), except `TRANSFER_FAILED` (§8.6).

---

## 9. Loan Business Rules

**9.1 State machine**
```
DRAFT ──submit──► PENDING_REVIEW ──review(AUTO/APPROVE)──► APPROVED ──accept──► ACTIVE ──last repayment──► CLOSED
  │                    │                   │
  │                    └──review(REJECT / rules fail)──► REJECTED
  └──cancel──► CANCELLED   (also from PENDING_REVIEW and APPROVED)
```
Any other transition → `409 INVALID_STATE`. Editing endpoints (`details`, `income-details`, `documents`, `guarantor`) work in `DRAFT` only.

**9.2 Eligibility / rejection codes** (evaluated by `AUTO`; *all* failing rules are collected into `rejection_codes`; any code ⇒ `REJECTED`)

| Code | Condition |
|---|---|
| `LOW_INCOME` | `monthly_income < 10000` |
| `EMI_TOO_HIGH` | `reference_emi / monthly_income > 0.50` (reference EMI = EMI at 9.00 %) |
| `AMOUNT_EXCEEDS_LIMIT` | `requested_amount > 20 × monthly_income` |
| `TOO_MANY_ACTIVE_LOANS` | user already has ≥ 2 loans with status `ACTIVE` |
| `GUARANTOR_SAME_AS_APPLICANT` | `guarantor_aadhar == aadhar_number` |

`APPROVE` (manual override) always approves using the computed rate; `REJECT` always rejects with `rejection_codes=["MANUAL_REJECTION"]`. `approved_amount = requested_amount` (no partial approvals).

**9.3 Interest rate (annual %)**
`final_rate = max(5.00, 9.00 − income_discount − guarantor_discount − tenure_discount − loyalty_discount)`

| Discount | Rule |
|---|---|
| `income_discount` | `ratio = reference_emi / monthly_income`: `≤ 0.20` → 2.00 · `≤ 0.35` → 1.00 · else 0.00 |
| `guarantor_discount` | SPOUSE, PARENT, SIBLING, CHILD → 1.00 · OTHER_RELATIVE → 0.50 · FRIEND, COLLEAGUE → 0.00 |
| `tenure_discount` | `≤ 12` months → 1.00 · `≤ 24` → 0.50 · else 0.00 |
| `loyalty_discount` | 1.00 if the user has ≥ 1 loan with status `CLOSED`, else 0.00 |

Stored in `rate_breakdown` (strings, 2 decimals).

**9.4 EMI & schedule (`loan_engine.py`, pure functions, `Decimal`, prec ≥ 28, `ROUND_HALF_UP`)**
```
r   = annual_rate / 12 / 100
EMI = round2( P · r · (1+r)^n / ((1+r)^n − 1) )
balance = P
for k in 1..n:
    interest = round2(balance · r)
    if k < n: principal = EMI − interest ; emi_k = EMI
    else:     principal = balance        ; emi_k = principal + interest     # last row absorbs rounding
    balance = balance − principal      # row stores balance_after
total_payable = Σ emi_k ;  total_interest = total_payable − P ;  loans.emi_amount = EMI
first due_date = disbursement date (UTC) + 1 calendar month; then monthly (clamp day to month end)
```
**Reference vectors (QA must recompute independently with Decimal; ±0.01 tolerance only on the EMI cross-check):** `P=50000, rate=9.00, n=12 → EMI 4372.57` · `P=50000, rate=5.00, n=12 → EMI 4280.37`. Invariant: `Σ principal_component == P` exactly; final `balance_after == 0.00`.

**9.5 Worked example (matches the wireframe’s “5 %”)**: income 60 000, amount 50 000, 12 months, guarantor PARENT, no closed loans → ratio ≈ 0.073 (→ 2.00) + 1.00 + 1.00 + 0.00 ⇒ `9.00 − 4.00 = 5.00 %`.

**9.6 Disbursement (`accept`)** — one DB transaction: lock loan (`FOR UPDATE`), verify `APPROVED`, `move_money(LOAN_DISBURSEMENT, from=system account 1, to=loan.account_id, amount=approved_amount, loan_id=…)`, insert all schedule rows, set `status='ACTIVE'`, `disbursed_at`, notification `LOAN_DISBURSED`.

**9.7 Repayment (`repay`)** — one DB transaction: lock loan → lock accounts (via `move_money`) → pick lowest `PENDING` installment → `move_money(LOAN_REPAYMENT, from=user account, to=system account 1, amount=emi_amount, loan_id=…)` → mark installment `PAID` (`paid_at`, `paid_txn_id`) → if none left: `status='CLOSED'`, `closed_at` → notifications `REPAYMENT_PAID` (+ `LOAN_CLOSED`). Failures follow §8.6 (recorded `FAILED` row carries `loan_id`).

**9.8 Applicant checks** (`details`): `date_of_birth` ⇒ age ≥ 21 on today's date; `requested_amount` in [5 000, 500 000]; `tenure_months` ∈ {6,12,18,24,36}.

---

## 10. Internal Python Interfaces (exact signatures)

All modules live under `backend/`; imports are relative to `backend/` (e.g. `from services.ledger import move_money`).

**errors.py (01)**
```python
ERROR_STATUS: dict[str, int]                       # code -> HTTP status (Appendix B)
class ApiError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None, http_status: int | None = None)  # status defaults from ERROR_STATUS
class SimulatedNetworkError(Exception):  # attr: point: str
    def __init__(self, point: str)
class SimulatedResponseDropped(Exception): ...
def register_error_handlers(app) -> None           # ApiError→envelope, SimulatedNetworkError→503 SIMULATED_NETWORK_FAILURE,
                                                   # SimulatedResponseDropped→504 NETWORK_TIMEOUT, 404→NOT_FOUND, 405→METHOD_NOT_ALLOWED, Exception→500 INTERNAL_ERROR
```
**responses.py (01):** `ok(data: dict, status: int = 200)` → Flask response; `paginated(items: list, page: int, page_size: int, total_items: int, **extra) -> dict` (returns the `data` dict).
**money.py (01):** `parse_money(value, field="amount", min_value=None, max_value=None) -> Decimal` (raises `ApiError(VALIDATION_ERROR)`); `money_str(d: Decimal) -> str`; `round2(d: Decimal) -> Decimal`.
**utils.py (01):** `utcnow() -> datetime`; `iso(dt) -> str | None`; `new_ref() -> str` (uuid4); `mask_name(full_name: str) -> str`; `add_months(d: date, n: int) -> date`; `validate_fields(data: dict, rules: dict) -> dict` (raises `VALIDATION_ERROR` with `details.fields`).
**middleware.py (01):** `require_user` (decorator; sets `flask.g.user_id: int`); `get_page_args() -> tuple[int, int]`.
**db.py (01)**
```python
def get_connection()                                # pooled, utf8mb4, time_zone '+00:00', READ COMMITTED (pool size 32)
def transaction()                                   # contextmanager -> yields dict-cursor; COMMIT on success, ROLLBACK on any exception (then re-raise)
def run_transaction(fn, retries: int = 3)           # fn(cur) -> result ; retries on errno 1213/1205 (§8.7)
def fetch_one(sql: str, params=None) -> dict | None
def fetch_all(sql: str, params=None) -> list[dict]
def execute(sql: str, params=None) -> int           # autocommit single non-financial statement; returns lastrowid
```
**services/notify.py (01):** `create_notification(cur, user_id: int, ntype: str, title: str, message: str, related_ref: str | None = None) -> int`
**init_db.py (01):** `create_schema()`, `seed()`, `reset_database()`; CLI `python backend/init_db.py [--no-seed]`.
**services/ledger.py (02)**
```python
def move_money(cur, *, txn_type: str, from_account_id: int, to_account_id: int, amount: Decimal,
               description: str | None = None, loan_id: int | None = None, related_txn_id: int | None = None,
               idempotency_key: str | None = None, initiated_by: int | None = None,
               simulate_failure: str | None = None) -> dict          # §8.5 ; caller owns the transaction
def record_failed_txn(*, txn_type: str, from_account_id: int | None, to_account_id: int | None, amount: Decimal,
                      failure_code: str, failure_reason: str, description: str | None = None,
                      loan_id: int | None = None, initiated_by: int | None = None,
                      notify_user_id: int | None = None) -> str | None   # own transaction; never raises; returns txn_ref
def find_by_idempotency_key(cur, key: str, user_id: int) -> dict | None   # Transaction object (replay) or None
def get_transaction_dict(txn_ref: str, viewer_user_id: int | None = None, cur=None, account_id: int | None = None) -> dict  # Transaction shape §6
```
**services/failure_sim.py (02):** `maybe_fail(point: str, override: str | None = None) -> None` (raises `SimulatedNetworkError`); `maybe_drop_response(override: str | None = None) -> None` (raises `SimulatedResponseDropped`); `get_global() -> dict` (`{"mode","probability"}`); `set_global(mode: str, probability: float | None = None) -> dict`.
**services/transfer_service.py (02):** `transfer(user_id, from_account_number, to_account_number, amount, note, idempotency_key, simulate_failure) -> tuple[dict, int]` (payload, http_status); `deposit(user_id, account_number, amount, note, idempotency_key, simulate_failure) -> tuple[dict, int]`; `reverse(user_id, txn_ref, idempotency_key, simulate_failure) -> tuple[dict, int]`; `list_transactions(user_id, filters: dict, page: int, page_size: int) -> dict`; `get_transaction_detail(user_id, txn_ref) -> dict`.
**services/loan_engine.py (03):** `calc_emi(principal: Decimal, annual_rate: Decimal, n: int) -> Decimal`; `build_schedule(principal, annual_rate, n, first_due_date: date) -> list[dict]` (keys = `repayment_schedule` columns except ids/status); `compute_rate(monthly_income, principal, n, relationship, has_closed_loan: bool) -> dict` (the `rate_breakdown`); `evaluate_application(loan: dict, guarantor: dict, active_loans: int, has_closed_loan: bool) -> dict` (`{"decision","interest_rate","rejection_codes","rate_breakdown"}`).
**services/health_service.py (04):** `integrity_report() -> dict`; `health_summary() -> dict`.

---

## 11. Frontend Contract

**11.1 Pages**

| File | Owner | Endpoints used |
|---|---|---|
| `index.html` (login + register tabs) | 05 | `POST /auth/login`, `POST /auth/register` |
| `dashboard.html` | 05 | `GET /dashboard`, `GET/PUT /system/simulation`, `GET /system/integrity`, `POST /system/reset` |
| `profile.html` | 05 | `GET/PUT /users/me`, `GET/POST /accounts`, `PATCH /accounts/{id}/status` |
| `notifications.html` | 05 | `GET /notifications`, `POST /notifications/{id}/read`, `POST /notifications/read-all` |
| `send-money.html` | 06 | `GET /accounts`, `GET /accounts/lookup`, `POST /transactions/transfer` |
| `deposit.html` | 06 | `GET /accounts`, `POST /transactions/deposit` |
| `transactions.html` | 06 | `GET /transactions`, `GET /transactions/{ref}`, `POST /transactions/{ref}/reverse`, `GET /accounts` |
| `loans.html` | 07 | `GET /loans`, `GET /loans/{id}`, `GET /loans/{id}/schedule`, `POST /loans/{id}/repay`, `POST /loans/{id}/cancel` |
| `take-loan.html` | 07 | `GET /loans/config`, `GET /loans/estimate`, `GET /users/me`, `GET /accounts`, `POST /loans`, `PUT /loans/{id}/details`, `PUT …/income-details`, `POST …/documents`, `PUT …/guarantor`, `POST …/submit`, `POST …/review`, `POST …/accept`, `POST …/cancel`, `GET /loans/{id}` |

(Paths above are shown **without** the `/api` prefix — that is exactly how they are passed to `api.*`.)

**11.2 Layout (from wireframe).** Blue banking theme. **Top bar:** balance of the primary account (e.g. `₹10,000.00`) at left, `ABC Bank` logo/name at right. **Left sidebar** (in order): `Dashboard`, `Loans`, `Transactions`, `Profile`, `Notifications` (red dot when unread > 0). **Dashboard:** promo banner (`5% ONLY. Personal Loans with competitive rates.`), Profile tile, three quick actions **Take A Loan** (→ `take-loan.html`), **Send Money** (→ `send-money.html`), **Deposit Money** (→ `deposit.html`), bottom cards: *Recent Transactions*, *Status: All Good*, *System Health* (+ Demo Tools: simulation mode selector, “Verify Ledger”, “Reset Demo Data”).

**11.3 Design tokens (`css/style.css` `:root`)**
```css
--primary-dark:#0D4A94; --primary:#2E7CC4; --primary-light:#4F9EDB; --bg:#EAF2FA; --card:#FFFFFF;
--text:#1B2B3A; --muted:#6B7C8F; --success:#2E9E4F; --danger:#D64545; --warn:#E0A100; --radius:14px;
font-family:"Segoe UI", Roboto, Arial, sans-serif;
```
Shared classes (defined by 05llm, used by all): `.card .btn .btn-primary .btn-secondary .btn-danger .form-group .form-input .form-select .form-error .badge .badge-success .badge-warn .badge-danger .badge-info .table .grid .stepper .stepper-step .stepper-step.active .stepper-step.done .toast .modal .modal-backdrop .empty-state .spinner .quick-action`.

**11.4 Page skeleton (every page).**
```html
<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ABC Bank – …</title><link rel="stylesheet" href="css/style.css"></head>
<body><main id="page-content"> … page markup … </main>
<script src="js/api.js"></script><script src="js/common.js"></script><script src="js/<page>.js"></script></body></html>
```
`App.renderShell(activeKey)` wraps `#page-content` in the sidebar/top-bar layout.

**11.5 `js/api.js` (05) — global `api`.** Paths are relative to `/api` (write `api.get('/accounts')`, **not** `/api/accounts`).
```js
api.get(path, params?)      // params → query string; skips null/undefined/''
api.post(path, body?)       // JSON
api.put(path, body?)  api.patch(path, body?)  api.delete(path)
api.upload(path, formData)  // multipart, no manual Content-Type
// Each returns Promise<data>  (the `data` field of the envelope)
// Failure throws ApiClientError { name:'ApiClientError', code, message, status, details }
//   Network/parse failure → code 'NETWORK_ERROR', status 0
// Header X-User-Id is read from localStorage 'abc_user_id'. HTTP 401 AUTH_REQUIRED → clear storage, redirect to index.html.
```
**11.6 `js/common.js` (05) — global `App`.**
```js
App.requireLogin()                    // redirect to index.html if no abc_user_id
App.logout()
App.renderShell(activeKey)            // activeKey ∈ 'dashboard'|'loans'|'transactions'|'profile'|'notifications'; returns Promise<dashboardData>
App.refreshShell()                    // re-fetch /dashboard, update top-bar balance + notification dot
App.formatMoney("10000.00")           // → "₹10,000.00"   (string in, string out; no float math)
App.formatDate("2026-09-28") / App.formatDateTime("2026-09-28T10:15:30Z")   // en-IN, local time
App.toast(message, type)              // type ∈ 'success'|'error'|'info'
App.confirm(message)                  // Promise<boolean> (uses .modal, not window.confirm)
App.uuid()                            // crypto.randomUUID() with fallback
App.getUserId()  App.state           // { dashboard: <last dashboard data> }
```
localStorage keys (only these): `abc_user_id`, `abc_username`.
Sub-pages `send-money.html` & `deposit.html` use `activeKey='transactions'`; `take-loan.html` uses `'loans'`.

**11.7 Money-UX rules (Send/Deposit/Repay).** Generate `idempotency_key = App.uuid()` once per *form submission attempt*; reuse it for automatic retries; create a new one after success or after the user edits any field. On `NETWORK_TIMEOUT` show “Connection lost — checking…” and retry (same key) up to 3 × with 1 s delay. On `SIMULATED_NETWORK_FAILURE` show “Transaction rolled back. Your money is safe.” with a **Retry** button (same key). Disable the submit button while in flight.

---

## 12. Seed Data (`init_db.seed()`)

Passwords hashed via `werkzeug.security.generate_password_hash`. Seed inserts are done directly in Python but **must satisfy I1–I6**.

| user_id | username | password | full_name | account_id / number | balance |
|---|---|---|---|---|---|
| 1 | `__bank__` | (unusable) | ABC Bank | 1 / `000000000001` (system) | `-40000.00` |
| 2 | `alice` | `alice123` | Alice Sharma | 2 / `100000000001` | `10000.00` |
| 3 | `bob` | `bob123` | Bob Singh | 3 / `100000000002` | `5000.00` |
| 4 | `carol` | `carol123` | Carol Mehta | 4 / `100000000003` | `25000.00` |

Seed transactions (all `COMPLETED`, each with balanced ledger rows): DEPOSIT system→alice `11000.00`, DEPOSIT system→bob `4000.00`, DEPOSIT system→carol `25000.00` (description `Opening balance`), then TRANSFER alice→bob `1000.00` (description `Seed transfer`). Phones `9876500001..9876500003`, emails `<username>@abcbank.test`. `system_settings`: `sim_mode='NONE'`, `sim_probability='0.30'`.

---

## 13. Universal Verification Protocol (UVP)

Every task file (`00do0X.md`) repeats these and adds task-specific checks. **An agent may not report “done” while any check fails.**

1. **Version lock** — state the design version you built against (v1.0).
2. **Identifier audit** — list every table, column, endpoint, JSON key, error code, function, CSS class, localStorage key you use; `grep -n "<id>" structural_design.md` each. Zero hits = hallucination → remove or file a CHANGE REQUEST.
3. **Contract diff** — run the real thing and compare keys/types/status codes with §5–§7 and §10 line by line.
4. **Clean-start run** — fresh DB → `python backend/init_db.py` → `python backend/app.py` boots; feature works.
5. **Negative paths** — trigger every error code in your scope.
6. **Integrity gate** — `GET /api/system/integrity` returns `"ok": true` after your tests.
7. **No cross-edits** — DM the owner instead.
8. **Report** — `0Xto00.md` with evidence (commands + outputs).

---

## Appendix A — Endpoint Index (machine-readable; QA tools parse this table)

| # | Method | Path | Auth | Owner |
|---|---|---|---|---|
| 1 | POST | /api/auth/register | no | 04 |
| 2 | POST | /api/auth/login | no | 04 |
| 3 | GET | /api/users/me | yes | 04 |
| 4 | PUT | /api/users/me | yes | 04 |
| 5 | GET | /api/accounts | yes | 04 |
| 6 | POST | /api/accounts | yes | 04 |
| 7 | GET | /api/accounts/lookup | yes | 04 |
| 8 | GET | /api/accounts/{account_id} | yes | 04 |
| 9 | PATCH | /api/accounts/{account_id}/status | yes | 04 |
| 10 | POST | /api/transactions/transfer | yes | 02 |
| 11 | POST | /api/transactions/deposit | yes | 02 |
| 12 | GET | /api/transactions | yes | 02 |
| 13 | GET | /api/transactions/{txn_ref} | yes | 02 |
| 14 | POST | /api/transactions/{txn_ref}/reverse | yes | 02 |
| 15 | GET | /api/loans/config | yes | 03 |
| 16 | GET | /api/loans/estimate | yes | 03 |
| 17 | POST | /api/loans | yes | 03 |
| 18 | GET | /api/loans | yes | 03 |
| 19 | GET | /api/loans/{loan_id} | yes | 03 |
| 20 | PUT | /api/loans/{loan_id}/details | yes | 03 |
| 21 | PUT | /api/loans/{loan_id}/income-details | yes | 03 |
| 22 | POST | /api/loans/{loan_id}/documents | yes | 03 |
| 23 | PUT | /api/loans/{loan_id}/guarantor | yes | 03 |
| 24 | POST | /api/loans/{loan_id}/submit | yes | 03 |
| 25 | POST | /api/loans/{loan_id}/review | yes | 03 |
| 26 | POST | /api/loans/{loan_id}/accept | yes | 03 |
| 27 | POST | /api/loans/{loan_id}/cancel | yes | 03 |
| 28 | GET | /api/loans/{loan_id}/schedule | yes | 03 |
| 29 | POST | /api/loans/{loan_id}/repay | yes | 03 |
| 30 | GET | /api/notifications | yes | 04 |
| 31 | POST | /api/notifications/{notification_id}/read | yes | 04 |
| 32 | POST | /api/notifications/read-all | yes | 04 |
| 33 | GET | /api/dashboard | yes | 04 |
| 34 | GET | /api/system/health | no | 04 |
| 35 | GET | /api/system/integrity | no | 04 |
| 36 | GET | /api/system/simulation | no | 04 |
| 37 | PUT | /api/system/simulation | no | 04 |
| 38 | POST | /api/system/reset | no | 04 |

## Appendix B — Error Codes

| Code | HTTP | Meaning |
|---|---|---|
| `VALIDATION_ERROR` | 400 | Missing/malformed input (`details.fields`) |
| `AUTH_REQUIRED` | 401 | Missing/unknown `X-User-Id` |
| `INVALID_CREDENTIALS` | 401 | Wrong username/password |
| `FORBIDDEN` | 403 | Not your resource / DEBUG_TOOLS off |
| `NOT_FOUND` | 404 | Unknown resource / route |
| `ACCOUNT_NOT_FOUND` | 404 | Unknown account number |
| `METHOD_NOT_ALLOWED` | 405 | Wrong HTTP method |
| `USERNAME_TAKEN` | 409 | Username exists |
| `EMAIL_TAKEN` | 409 | Email exists |
| `INVALID_STATE` | 409 | Action not allowed in current status |
| `INSUFFICIENT_FUNDS` | 422 | Balance too low |
| `ACCOUNT_NOT_ACTIVE` | 422 | Account frozen/closed |
| `SAME_ACCOUNT_TRANSFER` | 422 | from == to |
| `LIMIT_EXCEEDED` | 422 | Amount/account-count limit |
| `TXN_NOT_REVERSIBLE` | 422 | Reversal rules violated |
| `REVERSAL_FUNDS_UNAVAILABLE` | 422 | Recipient can’t cover the reversal |
| `LOAN_INCOMPLETE` | 422 | Missing loan application parts (`details.missing`) |
| `INTERNAL_ERROR` | 500 | Unhandled exception |
| `SIMULATED_NETWORK_FAILURE` | 503 | Injected failure, fully rolled back |
| `TXN_RETRY_EXHAUSTED` | 503 | Deadlock retries used up |
| `NETWORK_TIMEOUT` | 504 | Response dropped after commit (retry with same key) |

## Appendix C — Change Control
Change requests: `0Xto00.md` with heading `CHANGE REQUEST`, containing *what*, *why*, *impact on other agents*. 00llm answers in `memotoall.md` (global) or `00to0X.md` (private). Until answered, follow v1.0 exactly.
