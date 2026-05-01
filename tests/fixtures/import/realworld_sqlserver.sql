--
-- Real-world fixture: T-SQL (SQL Server) flavour. Common patterns in
-- the wild that the importer must tolerate:
--
--   • Bracketed identifiers ([dbo].[users])
--   • IDENTITY(1,1) primary key declarations
--   • NVARCHAR / DATETIME2 types
--   • CHECK constraints with single-quoted enum lists
--   • Column-level descriptions via sp_addextendedproperty (not parsed —
--     just survives the file without breaking anything)
--

CREATE TABLE [dbo].[employees] (
    [id]            INT             IDENTITY(1,1) NOT NULL,
    [email]         NVARCHAR(255)   NOT NULL,
    [first_name]    NVARCHAR(80)    NOT NULL,
    [last_name]     NVARCHAR(80)    NOT NULL,
    [hired_at]      DATETIME2       NULL,
    [status]        NVARCHAR(16)    NOT NULL CHECK (status IN ('Active','OnLeave','Terminated')),
    PRIMARY KEY ([id])
);

CREATE TABLE [dbo].[time_entries] (
    [id]            BIGINT          IDENTITY(1,1) NOT NULL,
    [employee_id]   INT             NOT NULL,
    [started_at]    DATETIME2       NOT NULL,
    [duration_min]  INT             NOT NULL,
    PRIMARY KEY ([id]),
    FOREIGN KEY ([employee_id]) REFERENCES [dbo].[employees]([id])
);

EXEC sp_addextendedproperty
    @name        = N'MS_Description',
    @value       = N'Employee directory — one row per active or former staff member.',
    @level0type  = N'SCHEMA',
    @level0name  = N'dbo',
    @level1type  = N'TABLE',
    @level1name  = N'employees';
