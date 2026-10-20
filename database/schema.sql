BEGIN;

-- Standalone MEATTRACK Inventory Database Schema
-- Dedicated schema for inventory operations, raw materials, recipes, batches, and movements.

CREATE TABLE accounts (
    account_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_type text NOT NULL
        CHECK (account_type IN ('owner', 'team_leader', 'admin', 'inventory_manager')),
    name text NOT NULL,
    email text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    profile_image_path text,
    profile_image_position_x numeric(5,2) NOT NULL DEFAULT 50,
    profile_image_position_y numeric(5,2) NOT NULL DEFAULT 50,
    profile_image_scale numeric(4,2) NOT NULL DEFAULT 1,
    team_leader_role text CHECK (team_leader_role IS NULL OR team_leader_role IN ('inventory', 'manager', 'staff')),
    is_active boolean NOT NULL DEFAULT true,
    activation_status text NOT NULL DEFAULT 'active' CHECK (activation_status IN ('pending', 'active')),
    activated_at timestamptz DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE activity_logs (
    activity_log_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id bigint REFERENCES accounts(account_id) ON UPDATE CASCADE ON DELETE SET NULL,
    actor_role text,
    action text NOT NULL,
    entity_type text,
    entity_id bigint,
    outcome text NOT NULL DEFAULT 'success' CHECK (outcome IN ('success', 'failure')),
    request_id text,
    source_key text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE inventory_items (
    item_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_type text NOT NULL CHECK (item_type IN ('raw_material', 'finished_product')),
    category text,
    name text NOT NULL,
    description text,
    unit text NOT NULL,
    base_price numeric(12,2) NOT NULL DEFAULT 0 CHECK (base_price >= 0 AND base_price NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)),
    quantity_available numeric(12,3) NOT NULL DEFAULT 0 CHECK (quantity_available >= 0),
    pack_size numeric(12,3),
    pack_size_unit text,
    pack_content_status text,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (item_type, name),
    CHECK (btrim(unit) <> ''),
    CHECK (item_type = 'finished_product' OR base_price = 0),
    CHECK (item_type = 'raw_material' OR quantity_available = 0),
    CONSTRAINT inventory_items_measurement_contract_check CHECK (
        (
            item_type = 'raw_material'
            AND unit IN ('kg', 'g', 'ml')
            AND pack_size IS NULL
            AND pack_size_unit IS NULL
            AND pack_content_status IS NULL
        )
        OR
        (
            item_type = 'finished_product'
            AND unit = 'pack'
            AND (
                (pack_content_status = 'declared' AND pack_size > 0 AND pack_size_unit IN ('g', 'kg', 'ml'))
                OR
                (pack_content_status = 'unknown_legacy' AND pack_size IS NULL AND pack_size_unit IS NULL)
            )
        )
    )
);

CREATE TABLE inventory_batches (
    batch_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_id bigint NOT NULL REFERENCES inventory_items(item_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    batch_code text NOT NULL UNIQUE,
    source_type text NOT NULL DEFAULT 'direct_received'
        CHECK (source_type IN ('direct_received', 'production')),
    quantity_received numeric(12,3) NOT NULL CHECK (quantity_received > 0),
    quantity_available numeric(12,3) NOT NULL CHECK (quantity_available >= 0),
    unit text NOT NULL,
    received_date date NOT NULL DEFAULT CURRENT_DATE,
    expiry_date date NOT NULL,
    quality_status text NOT NULL DEFAULT 'approved'
        CHECK (quality_status IN ('pending', 'approved', 'rejected', 'expired', 'spoiled')),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (quantity_available <= quantity_received),
    CONSTRAINT inventory_batches_whole_pack_check CHECK (
        quantity_received = trunc(quantity_received) AND quantity_available = trunc(quantity_available)
    ),
    CHECK (expiry_date >= received_date),
    CHECK (btrim(unit) <> '')
);

CREATE TABLE product_recipes (
    recipe_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_item_id bigint NOT NULL REFERENCES inventory_items(item_id) ON UPDATE CASCADE ON DELETE CASCADE,
    material_item_id bigint NOT NULL REFERENCES inventory_items(item_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    quantity_required numeric(12,3) NOT NULL CHECK (quantity_required > 0),
    unit text NOT NULL,
    UNIQUE (product_item_id, material_item_id),
    CHECK (btrim(unit) <> '')
);

CREATE TABLE inventory_movements (
    movement_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_id bigint NOT NULL REFERENCES inventory_items(item_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    affected_batch_id bigint REFERENCES inventory_batches(batch_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    production_batch_id bigint REFERENCES inventory_batches(batch_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    order_id bigint,
    movement_type text NOT NULL CHECK (movement_type IN (
        'opening_balance', 'raw_receipt', 'production_consumption',
        'production_output', 'direct_finished_receipt', 'sale_fulfillment',
        'owner_correction'
    )),
    quantity_delta numeric(12,3) NOT NULL,
    unit text NOT NULL,
    balance_before numeric(12,3) NOT NULL CHECK (balance_before >= 0),
    balance_after numeric(12,3) NOT NULL CHECK (balance_after >= 0),
    actor_account_id bigint REFERENCES accounts(account_id) ON UPDATE CASCADE ON DELETE SET NULL,
    actor_name text NOT NULL,
    note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (balance_after = balance_before + quantity_delta),
    CHECK (quantity_delta <> 0 OR movement_type = 'opening_balance'),
    CHECK (btrim(unit) <> ''),
    CHECK (btrim(actor_name) <> '')
);

CREATE TABLE alerts (
    alert_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    alert_type text NOT NULL
        CHECK (alert_type IN ('low_stock', 'near_expiry', 'expired_batch', 'forecast')),
    severity text NOT NULL DEFAULT 'warning'
        CHECK (severity IN ('info', 'warning', 'critical')),
    product_id bigint REFERENCES inventory_items(item_id) ON UPDATE CASCADE ON DELETE CASCADE,
    product_batch_id bigint REFERENCES inventory_batches(batch_id) ON UPDATE CASCADE ON DELETE CASCADE,
    raw_material_id bigint REFERENCES inventory_items(item_id) ON UPDATE CASCADE ON DELETE CASCADE,
    message text NOT NULL,
    status text NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'acknowledged', 'resolved')),
    triggered_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        product_id IS NOT NULL
        OR product_batch_id IS NOT NULL
        OR raw_material_id IS NOT NULL
    )
);

CREATE TABLE business_settings (
    setting_key text PRIMARY KEY CHECK (btrim(setting_key) <> ''),
    setting_value jsonb NOT NULL,
    updated_by_account_id bigint REFERENCES accounts(account_id) ON UPDATE CASCADE ON DELETE SET NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO business_settings (setting_key, setting_value) VALUES
    ('inventory.near_expiry_days', '7'::jsonb),
    ('inventory.critical_expiry_days', '2'::jsonb),
    ('notifications.owner_critical_alerts', 'true'::jsonb),
    ('business.name', '"MeatTrack Inventory"'::jsonb),
    ('business.contact_email', '""'::jsonb),
    ('business.contact_phone', '""'::jsonb);

CREATE TABLE notifications (
    notification_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recipient_account_id bigint REFERENCES accounts(account_id) ON UPDATE CASCADE ON DELETE CASCADE,
    recipient_role text CHECK (recipient_role IN ('owner', 'team-leader', 'team_leader', 'inventory', 'admin')),
    category text NOT NULL,
    severity text NOT NULL DEFAULT 'info' CHECK (severity IN ('info', 'warning', 'critical')),
    title text NOT NULL,
    message text NOT NULL,
    target_url text,
    source_type text,
    source_id bigint,
    dedupe_key text UNIQUE,
    read_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (recipient_account_id IS NOT NULL OR recipient_role IS NOT NULL),
    CHECK (btrim(category) <> ''),
    CHECK (btrim(title) <> ''),
    CHECK (btrim(message) <> '')
);

CREATE TABLE notification_recipients (
    notification_id bigint NOT NULL REFERENCES notifications(notification_id) ON UPDATE CASCADE ON DELETE CASCADE,
    account_id bigint NOT NULL REFERENCES accounts(account_id) ON UPDATE CASCADE ON DELETE CASCADE,
    read_at timestamptz,
    PRIMARY KEY (notification_id, account_id)
);

CREATE TABLE web_sessions (
    token_hash char(64) PRIMARY KEY,
    account_id bigint REFERENCES accounts(account_id) ON UPDATE CASCADE ON DELETE CASCADE,
    data jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(data) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    CHECK (length(token_hash) = 64)
);

CREATE TABLE security_events (
    security_event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_type text NOT NULL CHECK (btrim(event_type) <> ''),
    subject_key text NOT NULL CHECK (btrim(subject_key) <> ''),
    succeeded boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE user_consents (
    user_consent_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id bigint NOT NULL REFERENCES accounts(account_id) ON UPDATE CASCADE ON DELETE CASCADE,
    policy_version text NOT NULL,
    consent_source text NOT NULL,
    provider text,
    accepted_at timestamptz NOT NULL DEFAULT now(),
    CHECK (btrim(policy_version) <> ''),
    CHECK (btrim(consent_source) <> '')
);

-- Recipe integrity check trigger
CREATE OR REPLACE FUNCTION validate_product_recipe_measurements()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    product_type text;
    material_type text;
    material_unit text;
BEGIN
    SELECT item_type INTO product_type FROM inventory_items WHERE item_id = NEW.product_item_id;
    SELECT item_type, unit INTO material_type, material_unit FROM inventory_items WHERE item_id = NEW.material_item_id;
    IF product_type IS DISTINCT FROM 'finished_product' THEN
        RAISE EXCEPTION 'Recipe product must be a finished product.';
    END IF;
    IF material_type IS DISTINCT FROM 'raw_material' THEN
        RAISE EXCEPTION 'Recipe ingredient must be a raw material.';
    END IF;
    IF NEW.unit IS DISTINCT FROM material_unit THEN
        RAISE EXCEPTION 'Recipe unit must match the raw material stock unit.';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_validate_recipe_measurements
BEFORE INSERT OR UPDATE ON product_recipes
FOR EACH ROW EXECUTE FUNCTION validate_product_recipe_measurements();

-- Indexes for performance
CREATE INDEX ix_inventory_items_type_active ON inventory_items (item_type, is_active, name);
CREATE INDEX ix_inventory_batches_item_expiry ON inventory_batches (item_id, expiry_date, quantity_available);
CREATE INDEX ix_inventory_movements_item_created ON inventory_movements (item_id, created_at DESC);
CREATE INDEX ix_alerts_status_severity ON alerts (status, severity, triggered_at DESC);
CREATE INDEX ix_activity_logs_created ON activity_logs (created_at DESC);
CREATE INDEX ix_web_sessions_expires ON web_sessions (expires_at);

COMMIT;
