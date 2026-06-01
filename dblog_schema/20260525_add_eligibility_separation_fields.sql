-- Add eligibility-separation fields for the Harness policy update.
-- The policy separates analysis exclusion, trigger exclusion, and history
-- exclusion so a stored observation is not over-interpreted by downstream
-- analysis or future prompt construction.

USE lacp_db;

ALTER TABLE turn_node_logs
  ADD COLUMN IF NOT EXISTS history_eligible TINYINT NULL
    AFTER exclude_from_causal_trigger,
  ADD COLUMN IF NOT EXISTS history_exclusion_reason VARCHAR(512) NULL
    AFTER history_eligible,
  ADD COLUMN IF NOT EXISTS metric_trigger_eligibility JSON NULL
    AFTER metric_status;

ALTER TABLE metric_logs
  ADD COLUMN IF NOT EXISTS metric_trigger_eligibility JSON NULL
    AFTER exclude_from_causal_trigger;

CREATE INDEX IF NOT EXISTS idx_turn_node_history_eligible
  ON turn_node_logs (history_eligible);
