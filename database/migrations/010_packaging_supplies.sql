CREATE TABLE inventory_supply_items (
    supply_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL CHECK (char_length(btrim(name)) BETWEEN 1 AND 120),
    category text NOT NULL CHECK (char_length(btrim(category)) BETWEEN 1 AND 80),
    unit text NOT NULL CHECK (unit IN ('piece','pair','box','roll','pack','meter')),
    quantity_available numeric(12,3) NOT NULL DEFAULT 0 CHECK (quantity_available >= 0),
    initial_quantity numeric(12,3) NOT NULL CHECK (initial_quantity >= 0),
    creation_reference uuid NOT NULL UNIQUE,
    -- Account identifiers and names are snapshots; food-inventory account resets
    -- must not erase or change the separate supplies history.
    created_by_account_id bigint NOT NULL,
    created_at timestamptz NOT NULL,
    CHECK (unit='meter' OR (quantity_available=trunc(quantity_available) AND initial_quantity=trunc(initial_quantity)))
);
CREATE UNIQUE INDEX inventory_supply_name_unique ON inventory_supply_items(lower(name));

CREATE TABLE inventory_supply_movements (
    movement_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    supply_id bigint NOT NULL REFERENCES inventory_supply_items(supply_id) ON DELETE RESTRICT,
    submission_reference uuid NOT NULL UNIQUE,
    movement_type text NOT NULL CHECK (movement_type IN ('opening','stock_in','stock_out')),
    quantity_delta numeric(12,3) NOT NULL,
    unit text NOT NULL CHECK (unit IN ('piece','pair','box','roll','pack','meter')),
    balance_before numeric(12,3) NOT NULL CHECK (balance_before >= 0),
    balance_after numeric(12,3) NOT NULL CHECK (balance_after >= 0),
    actor_account_id bigint NOT NULL,
    actor_name text NOT NULL CHECK (btrim(actor_name)<>''),
    reason text NOT NULL CHECK (char_length(btrim(reason)) BETWEEN 1 AND 500),
    created_at timestamptz NOT NULL,
    CHECK (balance_after=balance_before+quantity_delta),
    CHECK ((movement_type IN ('opening','stock_in') AND quantity_delta>0)
        OR (movement_type='stock_out' AND quantity_delta<0)),
    CHECK (unit='meter' OR (quantity_delta=trunc(quantity_delta) AND balance_before=trunc(balance_before) AND balance_after=trunc(balance_after)))
);
CREATE INDEX inventory_supply_movements_date ON inventory_supply_movements(created_at,supply_id,movement_id);
CREATE INDEX inventory_supply_movements_item ON inventory_supply_movements(supply_id,created_at,movement_id);
CREATE TRIGGER supply_movements_immutable BEFORE UPDATE OR DELETE ON inventory_supply_movements
    FOR EACH ROW EXECUTE FUNCTION protect_inventory_history();
CREATE TRIGGER supply_movements_no_truncate BEFORE TRUNCATE ON inventory_supply_movements
    FOR EACH STATEMENT EXECUTE FUNCTION protect_inventory_history();

CREATE FUNCTION protect_supply_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(NEW.unit,NEW.initial_quantity,NEW.creation_reference,NEW.created_at,NEW.created_by_account_id)
        IS DISTINCT FROM ROW(OLD.unit,OLD.initial_quantity,OLD.creation_reference,OLD.created_at,OLD.created_by_account_id) THEN
        RAISE EXCEPTION 'Supply units and opening records cannot be changed.';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER supply_identity_locked BEFORE UPDATE ON inventory_supply_items
    FOR EACH ROW EXECUTE FUNCTION protect_supply_identity();
