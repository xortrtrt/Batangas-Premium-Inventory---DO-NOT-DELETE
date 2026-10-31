CREATE TABLE inventory_product_images (
    product_item_id bigint PRIMARY KEY REFERENCES inventory_items(item_id) ON DELETE RESTRICT,
    content_type text NOT NULL CHECK (content_type IN ('image/jpeg','image/png','image/webp')),
    image_data bytea NOT NULL CHECK (octet_length(image_data) BETWEEN 1 AND 2097152)
);
