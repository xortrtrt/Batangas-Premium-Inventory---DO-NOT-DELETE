ALTER TABLE inventory_movements ADD COLUMN raw_deduction_reference uuid;
CREATE UNIQUE INDEX ix_raw_deduction_reference
    ON inventory_movements(raw_deduction_reference) WHERE raw_deduction_reference IS NOT NULL;

ALTER TABLE inventory_movements DROP CONSTRAINT inventory_movements_movement_type_check;
ALTER TABLE inventory_movements ADD CONSTRAINT inventory_movements_movement_type_check
    CHECK (movement_type IN ('opening_balance', 'raw_receipt', 'production_consumption',
        'production_output', 'direct_finished_receipt', 'sale_fulfillment', 'owner_correction',
        'stock_dispatch', 'raw_deduction'));
ALTER TABLE inventory_movements ADD CONSTRAINT inventory_raw_deduction_check CHECK (
    (movement_type = 'raw_deduction') = (raw_deduction_reference IS NOT NULL)
    AND (movement_type <> 'raw_deduction' OR (
        quantity_delta < 0 AND actor_account_id IS NOT NULL
        AND note IS NOT NULL AND char_length(btrim(note)) BETWEEN 1 AND 500
    ))
);
