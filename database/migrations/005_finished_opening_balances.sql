ALTER TABLE inventory_batches ADD COLUMN opening_reference uuid;
CREATE UNIQUE INDEX ix_finished_opening_reference ON inventory_batches(opening_reference)
    WHERE opening_reference IS NOT NULL;
ALTER TABLE inventory_batches DROP CONSTRAINT inventory_batches_source_type_check;
ALTER TABLE inventory_batches ADD CONSTRAINT inventory_batches_source_type_check
    CHECK (source_type IN ('direct_received', 'production', 'opening_balance'));
ALTER TABLE inventory_batches ADD CONSTRAINT inventory_batches_opening_reference_check
    CHECK ((source_type = 'opening_balance') = (opening_reference IS NOT NULL));
