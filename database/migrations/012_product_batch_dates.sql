-- Batch labels are entered by staff and may repeat for other products or days.
-- Preserve existing receipt dates, identifiers, quantities, and movement history.
ALTER TABLE inventory_batches ADD COLUMN batch_date date;
UPDATE inventory_batches SET batch_date = received_date;
ALTER TABLE inventory_batches
    ALTER COLUMN batch_date SET NOT NULL,
    ALTER COLUMN batch_date SET DEFAULT CURRENT_DATE,
    ADD CONSTRAINT inventory_batches_batch_date_check CHECK (batch_date <= received_date);

ALTER TABLE inventory_batches DROP CONSTRAINT inventory_batches_batch_code_key;
CREATE UNIQUE INDEX inventory_batches_product_date_code_unique
    ON inventory_batches (item_id, batch_date, lower(btrim(batch_code)));
