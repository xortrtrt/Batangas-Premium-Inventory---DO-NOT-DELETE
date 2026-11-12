import base64
import re
from io import BytesIO
from PIL import Image

import pytest
from fastapi.testclient import TestClient

from app import database
from app.application import create_app
from app.repositories.inventory import add_raw_inventory_item, create_product_with_recipe
from app.security import hash_password
from app.uploads import validate_product_image


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP8f52BgYGBiYGBgYGBAQAXMQHanC5ZcwAAAABJRU5ErkJggg==')


@pytest.mark.parametrize('mime,content', [('image/svg+xml', b'<svg/>'), ('image/png', b'not an image'),
                                        ('image/jpeg', b''), ('image/png', PNG + b'x' * 2097152),
                                        ('image/jpeg', b'\xff\xd8\xff'), ('image/png', b'\x89PNG\r\n\x1a\n'),
                                        ('image/png', base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6rS8AAAAASUVORK5CYII='))],
                         ids=['svg', 'invalid-png', 'empty', 'oversized', 'truncated-jpeg', 'png-header', 'corrupt-png'])
def test_reject_invalid_product_images(mime, content):
    with pytest.raises(ValueError, match='Product image'):
        validate_product_image(mime, content)


def test_product_images_decode_pixels_and_match_declared_format(monkeypatch):
    from app import uploads
    for fmt, mime in [('PNG', 'image/png'), ('JPEG', 'image/jpeg'), ('WEBP', 'image/webp')]:
        output = BytesIO()
        Image.new('RGB', (12, 12), 'gold').save(output, format=fmt)
        content = output.getvalue()
        validate_product_image(mime, content)
        with pytest.raises(ValueError, match='valid JPG'):
            validate_product_image(mime, content[:len(content)//2])
        with pytest.raises(ValueError, match='valid JPG'):
            validate_product_image('image/jpeg' if fmt != 'JPEG' else 'image/png', content)
    monkeypatch.setattr(uploads, 'PRODUCT_IMAGE_MAX_PIXELS', 100)
    with pytest.raises(ValueError, match='16 megapixels'):
        validate_product_image('image/webp', content)


def test_recipe_image_upload_auth_validation_and_display(inventory_db):
    _, actor = inventory_db
    raw = add_raw_inventory_item('Image test meat', 'meat', 'kg', '10', actor)['raw_material_id']
    with database.get_transaction_cursor() as cur:
        cur.execute('UPDATE accounts SET password_hash=%s WHERE account_id=%s', (hash_password('Image-Test-123!'), actor))
    client = TestClient(create_app())
    assert client.get('/portal/inventory/products/1/image', follow_redirects=False).status_code == 303
    assert client.post('/portal/inventory/products', files={'product_image': ('photo.png', PNG, 'image/png')}).status_code == 403
    token = re.search(r'name="csrf-token" content="([^"]+)"', client.get('/login').text).group(1)
    client.post('/login', data={'email': 'inventory@test.invalid', 'password': 'Image-Test-123!', 'consent': 'yes', 'csrf_token': token})
    page = client.get('/portal/inventory/inventory')
    assert 'enctype="multipart/form-data"' in page.text and 'name="product_image"' in page.text
    token = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
    form = {'name': 'Photo product', 'category': 'Pork', 'material_item_id[]': str(raw),
            'quantity_required[]': '1', 'quantity_required_unit[]': 'kg', 'csrf_token': token}
    response = client.post('/portal/inventory/products', data=form, files={'product_image': ('bad.png', b'bad', 'image/png')})
    assert 'Product image must be a valid' in response.text
    assert database.fetch_one('SELECT count(*) n FROM inventory_items WHERE item_type=\'finished_product\'')['n'] == 0
    response = client.post('/portal/inventory/products', data=form, files={'product_image': ('photo.png', PNG, 'image/png')})
    assert 'Product recipe created successfully.' in response.text
    product = database.fetch_one("SELECT item_id FROM inventory_items WHERE item_type='finished_product'")['item_id']
    image_url = f'/portal/inventory/products/{product}/image'
    image = client.get(image_url)
    assert image.status_code == 200 and image.content == PNG and image.headers['content-type'] == 'image/png'
    assert image_url in client.get('/portal/inventory/finished-products').text
    assert image_url in client.get(f'/portal/inventory/product-details?product_id={product}').text
    assert client.get('/portal/inventory/products/999999/image').status_code == 404
    response = client.post('/portal/inventory/products', data=form, files={'product_image': ('again.png', PNG, 'image/png')})
    assert 'Product already exists.' in response.text
    assert database.fetch_one('SELECT count(*) n FROM inventory_product_images')['n'] == 1
    form['name'] = 'Plain product'
    response = client.post('/portal/inventory/products', data=form)
    assert 'Product recipe created successfully.' in response.text
    plain = database.fetch_one("SELECT item_id FROM inventory_items WHERE name='Plain Product'")['item_id']
    assert client.get(f'/portal/inventory/product-details?product_id={plain}').status_code == 200
    # A later recipe failure rolls back the image together with its new product.
    with pytest.raises(ValueError):
        create_product_with_recipe('Rollback product', 'Pork', [raw], ['1'], ['ml'], actor, product_image=('image/png', PNG))
    assert database.fetch_one('SELECT count(*) n FROM inventory_product_images')['n'] == 1
    assert database.fetch_one("SELECT count(*) n FROM inventory_items WHERE name='Rollback Product'")['n'] == 0
