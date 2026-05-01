--
-- Real-world fixture: Oracle DDL. Patterns the importer must tolerate:
--
--   • VARCHAR2 / NUMBER(p,s) / CLOB types (mapped via SQL_TO_XSD)
--   • Schema-qualified table names (HR.PATIENTS)
--   • Inline COMMENT 'text' is NOT valid in Oracle — uses
--     COMMENT ON COLUMN ... IS '...' instead (already supported)
--   • CONSTRAINT <name> PRIMARY KEY / FOREIGN KEY syntax
--

CREATE TABLE HR.PATIENTS (
    PATIENT_ID    NUMBER(10)        NOT NULL,
    MEDICAL_REC   VARCHAR2(40)      NOT NULL,
    FULL_NAME     VARCHAR2(120)     NOT NULL,
    DOB           DATE,
    NOTES         CLOB,
    CONSTRAINT pk_patients PRIMARY KEY (PATIENT_ID)
);

CREATE TABLE HR.ENCOUNTERS (
    ENCOUNTER_ID  NUMBER(10)        NOT NULL,
    PATIENT_ID    NUMBER(10)        NOT NULL,
    PROVIDER_ID   NUMBER(10)        NOT NULL,
    ENCOUNTER_AT  TIMESTAMP         NOT NULL,
    CONSTRAINT pk_encounters PRIMARY KEY (ENCOUNTER_ID),
    CONSTRAINT fk_enc_patient FOREIGN KEY (PATIENT_ID)
        REFERENCES HR.PATIENTS (PATIENT_ID)
);

COMMENT ON TABLE  HR.PATIENTS         IS 'Patient master — one row per individual under care.';
COMMENT ON COLUMN HR.PATIENTS.MEDICAL_REC IS 'Medical record number — globally unique within the health system.';
COMMENT ON COLUMN HR.PATIENTS.DOB         IS 'Date of birth — Confidential PHI under HIPAA §164.514.';
COMMENT ON COLUMN HR.ENCOUNTERS.ENCOUNTER_AT IS 'When the encounter occurred, recorded in the local timezone.';
