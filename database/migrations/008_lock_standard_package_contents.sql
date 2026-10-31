ALTER TABLE inventory_package_settings ADD COLUMN standard_locked_at timestamptz;
UPDATE inventory_package_settings s SET standard_locked_at=now()
WHERE s.mode='standard' AND EXISTS (
    SELECT 1 FROM inventory_package_components c WHERE c.package_item_id=s.package_item_id
);

CREATE FUNCTION protect_standard_package_settings() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.standard_locked_at IS NOT NULL THEN
        RAISE EXCEPTION 'Saved standard package contents cannot be changed.';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER standard_package_settings_locked BEFORE UPDATE OR DELETE ON inventory_package_settings
    FOR EACH ROW EXECUTE FUNCTION protect_standard_package_settings();

CREATE FUNCTION protect_standard_package_components() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE old_id bigint; new_id bigint;
BEGIN
    IF TG_OP<>'INSERT' THEN old_id:=OLD.package_item_id; END IF;
    IF TG_OP<>'DELETE' THEN new_id:=NEW.package_item_id; END IF;
    IF EXISTS(SELECT 1 FROM inventory_package_settings
        WHERE package_item_id IN (old_id,new_id) AND standard_locked_at IS NOT NULL) THEN
        RAISE EXCEPTION 'Saved standard package contents cannot be changed.';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER standard_package_components_locked BEFORE INSERT OR UPDATE OR DELETE ON inventory_package_components
    FOR EACH ROW EXECUTE FUNCTION protect_standard_package_components();
