SET FOREIGN_KEY_CHECKS=0;
DROP TABLE IF EXISTS system_settings, notifications, repayment_schedule, ledger_entries, transactions, guarantors, loan_documents, loans, accounts, users;
SET FOREIGN_KEY_CHECKS=1;

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
  role           ENUM('CUSTOMER','OFFICER') NOT NULL DEFAULT 'CUSTOMER',
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
