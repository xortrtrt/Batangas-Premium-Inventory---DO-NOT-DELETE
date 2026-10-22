-- Stock is counted in packs; recipes specify ingredient amounts per pack.
-- Prices and declared net contents are no longer part of the inventory catalog.
ALTER TABLE inventory_items DROP CONSTRAINT IF EXISTS inventory_items_measurement_contract_check;
ALTER TABLE inventory_items DROP COLUMN base_price;
ALTER TABLE inventory_items DROP COLUMN pack_size;
ALTER TABLE inventory_items DROP COLUMN pack_size_unit;
ALTER TABLE inventory_items DROP COLUMN pack_content_status;
ALTER TABLE inventory_items ADD CONSTRAINT inventory_items_unit_contract_check CHECK (
    (item_type = 'raw_material' AND unit IN ('kg', 'g', 'ml'))
    OR (item_type = 'finished_product' AND unit = 'pack')
);

-- Inventory logins may use a username without inventing an email address.
ALTER TABLE accounts ALTER COLUMN email DROP NOT NULL;
