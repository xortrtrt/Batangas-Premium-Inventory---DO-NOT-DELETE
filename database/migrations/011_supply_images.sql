ALTER TABLE inventory_supply_items ADD COLUMN creation_image_sha256 text
    CHECK (creation_image_sha256 IS NULL OR char_length(creation_image_sha256)=64);
CREATE TABLE inventory_supply_images (
    supply_id bigint PRIMARY KEY REFERENCES inventory_supply_items(supply_id) ON DELETE RESTRICT,
    content_type text NOT NULL CHECK (content_type IN ('image/jpeg','image/png','image/webp')),
    image_data bytea NOT NULL CHECK (octet_length(image_data) BETWEEN 1 AND 2097152)
);
