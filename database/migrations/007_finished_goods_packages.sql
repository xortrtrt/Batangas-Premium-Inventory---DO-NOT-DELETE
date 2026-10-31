-- Packages bundle existing finished packs; they are not manufactured stock.
UPDATE inventory_items SET category='Package'
WHERE item_type='finished_product' AND lower(name) IN
    ('area distributor''s package','area distributors package','resellers package','reseller package','trial package');
CREATE TABLE inventory_package_settings (
    package_item_id bigint PRIMARY KEY REFERENCES inventory_items(item_id) ON DELETE RESTRICT,
    mode text NOT NULL DEFAULT 'standard' CHECK(mode IN ('standard','customized')),
    revision integer NOT NULL DEFAULT 1 CHECK(revision>0)
);
INSERT INTO inventory_package_settings(package_item_id)
    SELECT item_id FROM inventory_items WHERE item_type='finished_product' AND category='Package';
CREATE TABLE inventory_package_components (
    package_item_id bigint NOT NULL REFERENCES inventory_package_settings(package_item_id) ON DELETE CASCADE,
    product_item_id bigint NOT NULL REFERENCES inventory_items(item_id) ON DELETE RESTRICT,
    quantity_per_package numeric(12,3) NOT NULL CHECK(quantity_per_package>0 AND quantity_per_package=trunc(quantity_per_package)),
    PRIMARY KEY(package_item_id,product_item_id), CHECK(package_item_id<>product_item_id)
);
CREATE TABLE inventory_package_dispatch_details (
    dispatch_id uuid PRIMARY KEY REFERENCES inventory_dispatches(dispatch_id) ON DELETE RESTRICT,
    package_name text NOT NULL,
    package_mode text NOT NULL CHECK(package_mode IN ('standard','customized')),
    package_revision integer NOT NULL
);
CREATE TABLE inventory_package_dispatch_lines (
    dispatch_id uuid NOT NULL REFERENCES inventory_package_dispatch_details(dispatch_id) ON DELETE RESTRICT,
    product_item_id bigint NOT NULL REFERENCES inventory_items(item_id) ON DELETE RESTRICT,
    product_name text NOT NULL,
    quantity_per_package numeric(12,3) NOT NULL CHECK(quantity_per_package>0 AND quantity_per_package=trunc(quantity_per_package)),
    total_packs numeric(12,3) NOT NULL CHECK(total_packs>0 AND total_packs=trunc(total_packs)),
    PRIMARY KEY(dispatch_id,product_item_id)
);
CREATE TRIGGER package_dispatch_details_immutable BEFORE UPDATE OR DELETE ON inventory_package_dispatch_details
    FOR EACH ROW EXECUTE FUNCTION protect_inventory_history();
CREATE TRIGGER package_dispatch_lines_immutable BEFORE UPDATE OR DELETE ON inventory_package_dispatch_lines
    FOR EACH ROW EXECUTE FUNCTION protect_inventory_history();
CREATE TRIGGER package_dispatch_details_no_truncate BEFORE TRUNCATE ON inventory_package_dispatch_details
    FOR EACH STATEMENT EXECUTE FUNCTION protect_inventory_history();
CREATE TRIGGER package_dispatch_lines_no_truncate BEFORE TRUNCATE ON inventory_package_dispatch_lines
    FOR EACH STATEMENT EXECUTE FUNCTION protect_inventory_history();

CREATE FUNCTION initialize_package_settings() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.item_type='finished_product' AND NEW.category='Package' THEN
        INSERT INTO inventory_package_settings(package_item_id) VALUES(NEW.item_id) ON CONFLICT DO NOTHING;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER inventory_package_settings_init AFTER INSERT OR UPDATE OF category ON inventory_items
    FOR EACH ROW EXECUTE FUNCTION initialize_package_settings();
