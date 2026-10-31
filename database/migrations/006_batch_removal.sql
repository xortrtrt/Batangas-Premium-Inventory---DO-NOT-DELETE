-- Archive batches without deleting immutable stock history.
ALTER TABLE inventory_batches
    ADD COLUMN removed_at timestamptz,
    ADD COLUMN removed_by_account_id bigint REFERENCES accounts(account_id) ON DELETE RESTRICT,
    ADD COLUMN removal_reason text;
ALTER TABLE inventory_batches ADD CONSTRAINT inventory_batch_removal_check CHECK (
    (removed_at IS NULL AND removed_by_account_id IS NULL AND removal_reason IS NULL)
    OR (removed_at IS NOT NULL AND removed_by_account_id IS NOT NULL
        AND removal_reason IS NOT NULL AND char_length(btrim(removal_reason)) BETWEEN 1 AND 500
        AND quantity_available = 0)
);
