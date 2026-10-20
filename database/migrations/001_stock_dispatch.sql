CREATE TABLE inventory_dispatches (
    dispatch_id uuid PRIMARY KEY,
    product_item_id bigint NOT NULL REFERENCES inventory_items(item_id) ON DELETE RESTRICT,
    quantity numeric(12,3) NOT NULL CHECK (quantity > 0 AND quantity = trunc(quantity)),
    note text NOT NULL CHECK (char_length(btrim(note)) BETWEEN 1 AND 500),
    actor_account_id bigint NOT NULL REFERENCES accounts(account_id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE inventory_movements ADD COLUMN dispatch_id uuid
    REFERENCES inventory_dispatches(dispatch_id) ON DELETE RESTRICT;
ALTER TABLE inventory_movements DROP CONSTRAINT inventory_movements_movement_type_check;
ALTER TABLE inventory_movements ADD CONSTRAINT inventory_movements_movement_type_check
    CHECK (movement_type IN ('opening_balance', 'raw_receipt', 'production_consumption',
        'production_output', 'direct_finished_receipt', 'sale_fulfillment', 'owner_correction', 'stock_dispatch'));
ALTER TABLE inventory_movements ADD CONSTRAINT inventory_dispatch_movement_check
    CHECK ((movement_type = 'stock_dispatch') = (dispatch_id IS NOT NULL));
CREATE UNIQUE INDEX ix_dispatch_batch ON inventory_movements(dispatch_id, affected_batch_id)
    WHERE dispatch_id IS NOT NULL;

CREATE OR REPLACE FUNCTION protect_inventory_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Inventory history is immutable; record a new movement instead.';
END $$;
CREATE TRIGGER inventory_movements_immutable BEFORE UPDATE OR DELETE ON inventory_movements
    FOR EACH ROW EXECUTE FUNCTION protect_inventory_history();
CREATE TRIGGER inventory_movements_no_truncate BEFORE TRUNCATE ON inventory_movements
    FOR EACH STATEMENT EXECUTE FUNCTION protect_inventory_history();
CREATE TRIGGER inventory_dispatches_immutable BEFORE UPDATE OR DELETE ON inventory_dispatches
    FOR EACH ROW EXECUTE FUNCTION protect_inventory_history();
CREATE TRIGGER inventory_dispatches_no_truncate BEFORE TRUNCATE ON inventory_dispatches
    FOR EACH STATEMENT EXECUTE FUNCTION protect_inventory_history();
