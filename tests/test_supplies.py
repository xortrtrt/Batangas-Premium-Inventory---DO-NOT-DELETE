from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date, timezone, timedelta
from uuid import uuid4
import re
import base64
from io import BytesIO
from PIL import Image

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app import database
from app.application import create_app
from app.business_time import business_today
from app.repositories.inventory import supplies
from app.security import hash_password


def create(actor, name='Gloves', unit='piece', amount='10', reference=None):
    return supplies.create_supply(name, 'Protective supplies', unit, amount, reference or str(uuid4()), actor)['supply_id']


def move(actor, item, kind='stock_out', amount='1', reason='Issued to staff', reference=None):
    return supplies.record_supply_movement(item, kind, amount, reason, reference or str(uuid4()), actor)


def supply_dialog(html, action):
    return re.split(r'<div\s+class="inventory-modal(?:\s[^"]*)?"', html.split(f'data-inventory-modal="{action}"', 1)[1], maxsplit=1)[0]


def test_supplies_balances_idempotency_and_food_separation(inventory_db):
    _, actor = inventory_db
    reference = str(uuid4())
    item = create(actor, reference=reference)
    assert supplies.create_supply('Gloves', 'Protective supplies', 'piece', '10', reference, actor)['already_recorded']
    with pytest.raises(ValueError, match='different item details'):
        supplies.create_supply('Other gloves', 'Protective supplies', 'piece', '10', reference, actor)
    ref = str(uuid4())
    assert not move(actor, item, amount='4', reference=ref)['already_recorded']
    assert move(actor, item, amount='4', reference=ref)['already_recorded']
    with pytest.raises(ValueError, match='different movement details'):
        move(actor, item, amount='3', reference=ref)
    move(actor, item, kind='stock_in', amount='2', reason='Received delivery')
    rows = supplies.supplies_page(business_today())
    row = rows['items'][0]
    assert (row['opening_balance'], row['stock_in'], row['stock_out'], row['closing_balance'], row['quantity_available']) == (0, 12, 4, 8, 8)
    assert len(row['movements']) == 3 and row['movements'][0]['reason'] == 'Opening stock'
    assert database.fetch_one('SELECT count(*) n FROM inventory_movements')['n'] == 0
    assert database.fetch_one('SELECT count(*) n FROM inventory_items')['n'] == 0
    assert database.fetch_one('SELECT count(*) n FROM inventory_batches')['n'] == 0


def test_supplies_validation_units_limits_and_unique_variants(inventory_db):
    _, actor = inventory_db
    for unit in ('piece', 'pair', 'box', 'roll', 'pack'):
        item = create(actor, name=f'Counting {unit}', unit=unit, amount='0')
        for amount in ('0.5', '-1', '1e2', 'nan', '9999999999', '1.0001', '0'):
            with pytest.raises(ValueError):
                move(actor, item, kind='stock_in', amount=amount)
    meter = create(actor, name='Tape meters', unit='meter', amount='1.125')
    move(actor, meter, amount='0.125')
    assert next(x for x in supplies.supply_choices() if x['supply_id'] == meter)['quantity_available'] == 1
    for args in [('', 'pack', '0'), ('Bad unit', 'kg', '0'), ('Negative', 'piece', '-1'), ('Fraction', 'box', '0.1')]:
        with pytest.raises(ValueError):
            create(actor, name=args[0], unit=args[1], amount=args[2])
    create(actor, name='T-shirt — Medium')
    create(actor, name='T-shirt — Large')
    with pytest.raises(ValueError, match='already exists'):
        create(actor, name='t-SHIRT — medium')
    with pytest.raises(ValueError, match='Sign in'):
        create(None)
    with pytest.raises(ValueError, match='Invalid submission reference'):
        move(actor, meter, reference='bad')
    with pytest.raises(ValueError, match='Reason'):
        move(actor, meter, reason=' ')
    with pytest.raises(ValueError, match='Choose'):
        move(actor, 10**30)
    maximum = create(actor, name='Maximum', unit='meter', amount='999999999.999')
    with pytest.raises(ValueError, match='limit'):
        move(actor, maximum, kind='stock_in', amount='0.001')


def test_supplies_concurrent_stock_out_cannot_overspend(inventory_db):
    _, actor = inventory_db
    item = create(actor)
    def attempt(_):
        try:
            move(actor, item, amount='6')
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(attempt, range(2))) == [False, True]
    assert supplies.supply_choices()[0]['quantity_available'] == 4
    assert database.fetch_one('SELECT count(*) n FROM inventory_supply_movements')['n'] == 2


def test_supplies_concurrent_replay_and_item_creation(inventory_db):
    _, actor = inventory_db
    reference = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as workers:
        result = list(workers.map(lambda _: supplies.create_supply('Gloves', 'PPE', 'piece', '10', reference, actor), range(2)))
    assert sorted(r['already_recorded'] for r in result) == [False, True]
    item = result[0]['supply_id']
    reference = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as workers:
        result = list(workers.map(lambda _: move(actor, item, amount='2', reference=reference), range(2)))
    assert sorted(r['already_recorded'] for r in result) == [False, True]
    assert supplies.supply_choices()[0]['quantity_available'] == 8


def test_supplies_atomic_rollback_and_immutable_history(inventory_db, monkeypatch):
    _, actor = inventory_db
    item = create(actor)
    original = supplies._insert_movement
    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise ValueError('Simulated failure')
    with monkeypatch.context() as patch:
        patch.setattr(supplies, '_insert_movement', fail_after_write)
        with pytest.raises(ValueError, match='Simulated'):
            move(actor, item)
        with pytest.raises(ValueError, match='Simulated'):
            create(actor, name='Rolled back item')
    assert len(supplies.supply_choices()) == 1 and supplies.supply_choices()[0]['quantity_available'] == 10
    assert database.fetch_one('SELECT count(*) n FROM inventory_supply_movements')['n'] == 1
    for statement in ('UPDATE inventory_supply_movements SET reason=\'Changed\'',
                      'DELETE FROM inventory_supply_movements', 'TRUNCATE inventory_supply_movements',
                      "UPDATE inventory_supply_items SET unit='box'"):
        with pytest.raises(psycopg2.Error):
            with database.get_transaction_cursor() as cur:
                cur.execute(statement)


def test_supplies_daily_manila_midnight_and_no_movement_days(inventory_db, monkeypatch):
    _, actor = inventory_db
    moment = datetime(2026, 1, 1, 15, 59, 59, tzinfo=timezone.utc)
    monkeypatch.setattr(supplies, 'business_now', lambda: moment)
    item = create(actor)
    create(actor, name='Empty bags', amount='0')
    moment = datetime(2026, 1, 1, 16, 0, 0, tzinfo=timezone.utc)
    move(actor, item, kind='stock_in', amount='5')
    move(actor, item, amount='3')
    moment += timedelta(days=1)
    create(actor, name='Later stickers', amount='2')
    first = supplies.supplies_page(date(2026, 1, 1), q='Gloves')['items'][0]
    assert (first['opening_balance'], first['stock_in'], first['stock_out'], first['closing_balance']) == (0, 10, 0, 10)
    second = supplies.supplies_page(date(2026, 1, 2), q='Gloves')['items'][0]
    assert (second['opening_balance'], second['stock_in'], second['stock_out'], second['closing_balance']) == (10, 5, 3, 12)
    assert len(second['movements']) == 2
    assert supplies.supplies_page(date(2026, 1, 2))['total'] == 2
    assert supplies.supplies_page(date(2025, 12, 31))['total'] == 0
    quiet = supplies.supplies_page(date(2026, 1, 4), q='Gloves')['items'][0]
    assert (quiet['opening_balance'], quiet['stock_in'], quiet['stock_out'], quiet['closing_balance']) == (12, 0, 0, 12)
    assert quiet['movements'] == []
    assert supplies.supplies_page(date(2026, 1, 4), page=99, page_size=1)['page'] == 3


def test_supplies_http_auth_csrf_actor_dates_and_tabs(inventory_db):
    _, actor = inventory_db
    with database.get_transaction_cursor() as cur:
        cur.execute('UPDATE accounts SET password_hash=%s WHERE account_id=%s', (hash_password('Supplies-Test-123!'), actor))
    client = TestClient(create_app())
    assert client.get('/portal/inventory/supplies', follow_redirects=False).status_code == 303
    assert client.post('/portal/inventory/supplies/items', data={}).status_code == 403
    assert client.post('/portal/inventory/supplies/movements', data={}).status_code == 403
    token = re.search(r'name="csrf-token" content="([^"]+)"', client.get('/login').text).group(1)
    client.post('/login', data={'email': 'inventory@test.invalid', 'password': 'Supplies-Test-123!', 'consent': 'yes', 'csrf_token': token})
    page = client.get('/portal/inventory/supplies')
    assert page.status_code == 200 and 'Packaging &amp; supplies' in page.text
    content = re.split(r'<section\s+data-portal-content', page.text, maxsplit=1)[1]
    assert 'data-supply-form' not in content and 'name="supply_image"' not in content
    entry = client.get('/portal/inventory/supplies-manage')
    assert entry.status_code == 200 and 'name="initial_quantity"' in entry.text
    assert entry.text.count('data-inventory-modal-open=') == 4
    assert 'class="inventory-workspace"' in entry.text
    assert 'supplies-hero' not in entry.text and 'movement-categories' not in entry.text
    assert 'finished-products-browser' in page.text
    movements = client.get('/portal/inventory/supplies-movements')
    assert movements.status_code == 200 and 'Movement date' in movements.text
    assert 'data-supply-form' not in movements.text and 'name="supply_image"' not in movements.text
    for role in ('owner', 'team-leader'):
        for section in ('supplies', 'supplies-manage', 'supplies-movements'):
            assert client.get(f'/portal/{role}/{section}').status_code == 200
    token = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
    form = {'name': 'Bags', 'category': 'Packaging', 'unit': 'piece', 'initial_quantity': '4',
            'submission_reference': str(uuid4()), 'csrf_token': token, 'actor_account_id': '99999'}
    assert 'Supply item created' in client.post('/portal/inventory/supplies/items', data=form).text
    item = supplies.supply_choices()[0]['supply_id']
    form = {'supply_id': item, 'movement_type': 'stock_out', 'quantity': '2', 'reason': 'For packing',
            'submission_reference': str(uuid4()), 'csrf_token': token, 'actor_account_id': '99999', 'actor_name': 'Forged'}
    assert 'Balance updated' in client.post('/portal/inventory/supplies/movements', data=form).text
    recorded = database.fetch_one("SELECT * FROM inventory_supply_movements WHERE movement_type='stock_out'")
    assert recorded['actor_account_id'] == actor and recorded['actor_name'] == 'Test Inventory'
    form['date'] = '2020-01-01'
    assert 'current Manila date' in client.post('/portal/inventory/supplies/movements', data=form).text
    assert supplies.supply_choices()[0]['quantity_available'] == 2
    for tab in ('items', 'stock_in', 'stock_out', 'daily'):
        response = client.get(f'/portal/inventory/supplies?tab={tab}')
        assert response.status_code == 200 and 'Bags' in response.text
        if tab in {'stock_in', 'stock_out'}:
            assert f'data-inventory-initial-modal="{tab}"' in response.text
            assert f'name="movement_type" value="{tab}"' in response.text
            assert 'type="radio" name="movement_type"' not in response.text
            assert f'Save {tab.replace("_", " ")}' in response.text
    assert 'name="movement_type" value="stock_in"' in client.get('/portal/inventory/supplies?tab=stock').text
    daily = client.get('/portal/inventory/supplies?tab=daily').text
    assert 'class="movement-list"' in daily and 'For packing' in daily
    assert 'supplies-day-item' not in daily
    assert 'Test Inventory' in daily and 'Forged' not in daily
    assert client.get('/portal/inventory/supplies?tab=daily&date=bad').status_code == 400
    assert client.get('/portal/inventory/supplies?tab=daily&date=9999-01-01').status_code == 400
    assert client.get('/portal/inventory/supplies?tab=daily&q=Missing').status_code == 200
    assert client.get('/portal/owner/supplies').status_code == 200
    assert client.get('/portal/team-leader/supplies').status_code == 200
    with database.get_transaction_cursor() as cur:
        cur.execute("UPDATE accounts SET name='Renamed Staff' WHERE account_id=%s", (actor,))
    assert 'Test Inventory' in client.get('/portal/inventory/supplies?tab=daily').text


def test_food_reset_preserves_separate_supplies(inventory_db, tmp_path):
    from tools.reset_inventory import reset_inventory
    dsn, actor = inventory_db
    create(actor)
    with database.get_transaction_cursor() as cur:
        cur.execute("INSERT INTO inventory_items(item_type,name,category,unit) VALUES('finished_product','Food product','Beef','pack')")
    backup = tmp_path / 'test.dump'
    backup.write_bytes(b'PGDMP' + b'test-only-backup-header' * 4)
    credentials = [{'username': f'BPadmin{i}', 'password': f'Supplies-Reset-{i}-Unique!'} for i in range(1,5)]
    reset_inventory(dsn, apply=True, backup=backup, credentials=credentials)
    assert supplies.supply_choices()[0]['quantity_available'] == 10
    assert supplies.supplies_page(business_today())['items'][0]['movements'][0]['actor_name'] == 'Test Inventory'


SUPPLY_PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP8f52BgYGBiYGBgYGBAQAXMQHanC5ZcwAAAABJRU5ErkJggg==')


def test_supply_photos_atomic_create_replay_and_replace(inventory_db, monkeypatch):
    _, actor = inventory_db
    ref = str(uuid4())
    image = ('image/png', SUPPLY_PNG)
    first = supplies.create_supply('Photo bags', 'Packaging', 'piece', '10', ref, actor, image=image)
    item = first['supply_id']
    assert supplies.supply_choices()[0]['has_image'] is True
    assert supplies.supplies_page(business_today())['items'][0]['has_image'] is True
    assert supplies.create_supply('Photo bags', 'Packaging', 'piece', '10', ref, actor, image=image)['already_recorded']
    with pytest.raises(ValueError, match='different item details'):
        supplies.create_supply('Photo bags', 'Packaging', 'piece', '10', ref, actor)
    replacement_bytes = BytesIO()
    Image.new('RGB', (2,2), 'blue').save(replacement_bytes, format='PNG')
    replacement = ('image/png', replacement_bytes.getvalue())
    supplies.save_supply_image(item, replacement, actor)
    assert supplies.create_supply('Photo bags', 'Packaging', 'piece', '10', ref, actor, image=image)['already_recorded']
    assert supplies.supply_choices()[0]['quantity_available'] == 10
    assert database.fetch_one('SELECT count(*) n FROM inventory_supply_movements')['n'] == 1
    assert bytes(database.fetch_one('SELECT image_data FROM inventory_supply_images')['image_data']) == replacement[1]
    def fail(*args, **kwargs):
        raise ValueError('Simulated stock failure')
    monkeypatch.setattr(supplies, '_insert_movement', fail)
    with pytest.raises(ValueError, match='Simulated'):
        supplies.create_supply('Rollback photo', 'Packaging', 'piece', '1', str(uuid4()), actor, image=image)
    assert database.fetch_one('SELECT count(*) n FROM inventory_supply_items')['n'] == 1
    assert database.fetch_one('SELECT count(*) n FROM inventory_supply_images')['n'] == 1


def test_supply_photo_validation(inventory_db):
    _, actor = inventory_db
    item = create(actor)
    for image in [('image/svg+xml', b'<svg/>'), ('image/png', b'bad'), ('image/png', SUPPLY_PNG+b'x'*2097152),
                  ('image/png', b'\x89PNG\r\n\x1a\n'), ('image/jpeg', b'\xff\xd8\xff')]:
        with pytest.raises(ValueError, match='Supply image'):
            supplies.save_supply_image(item, image, actor)
    with pytest.raises(ValueError, match='Sign in'):
        supplies.save_supply_image(item, ('image/png', SUPPLY_PNG), None)
    with pytest.raises(ValueError, match='valid supply item'):
        supplies.save_supply_image(99999, ('image/png', SUPPLY_PNG), actor)
    assert database.fetch_one('SELECT count(*) n FROM inventory_supply_images')['n'] == 0
    assert supplies.supply_choices()[0]['quantity_available'] == 10


def test_supply_photo_http_and_redesign(inventory_db):
    _, actor = inventory_db
    with database.get_transaction_cursor() as cur:
        cur.execute('UPDATE accounts SET password_hash=%s WHERE account_id=%s', (hash_password('Supply-Photo-123!'), actor))
    client = TestClient(create_app())
    assert client.get('/portal/inventory/supplies/1/image', follow_redirects=False).status_code == 303
    assert client.post('/portal/inventory/supplies/1/image', data={}).status_code == 403
    token = re.search(r'name="csrf-token" content="([^"]+)"', client.get('/login').text).group(1)
    client.post('/login', data={'email': 'inventory@test.invalid', 'password': 'Supply-Photo-123!', 'consent': 'yes', 'csrf_token': token})
    page = client.get('/portal/inventory/supplies')
    assert 'finished-products-browser' in page.text and 'name="supply_image"' not in page.text
    assert 'name="supply_image"' in client.get('/portal/inventory/supplies-manage').text
    token = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
    form = {'name': 'Photo gloves', 'category': 'PPE', 'unit': 'piece', 'initial_quantity': '8',
            'submission_reference': str(uuid4()), 'csrf_token': token}
    result = client.post('/portal/inventory/supplies/items', data=form,
                         files={'supply_image': ('gloves.png', SUPPLY_PNG, 'image/png')})
    assert 'Supply item created' in result.text
    item = supplies.supply_choices()[0]['supply_id']
    image_url = f'/portal/inventory/supplies/{item}/image'
    image = client.get(image_url)
    assert image.content == SUPPLY_PNG and image.headers['content-type'] == 'image/png'
    assert image.headers['cache-control'] == 'private, no-cache'
    for tab in ('items','daily','stock_in','stock_out'):
        response = client.get(f'/portal/inventory/supplies?tab={tab}')
        assert response.status_code == 200
        if tab == 'daily':
            assert 'Photo gloves' in response.text and 'class="movement-list"' in response.text
        else:
            assert image_url in response.text
    result = client.post(image_url, data={'csrf_token': token}, files={'supply_image': ('other.png', SUPPLY_PNG, 'image/png')})
    assert 'Supply photo updated' in result.text
    assert supplies.supply_choices()[0]['quantity_available'] == 8
    assert 'Choose a supply image' in client.post(image_url, data={'csrf_token': token}).text
    assert client.get('/portal/inventory/supplies/999999/image').status_code == 404


def test_failed_stock_out_preserves_draft_and_safe_retry(inventory_db):
    _, actor = inventory_db
    with database.get_transaction_cursor() as cur:
        cur.execute('UPDATE accounts SET password_hash=%s WHERE account_id=%s', (hash_password('Supply-Draft-123!'), actor))
    first = create(actor, name='Alpha bags', amount='1')
    gloves = create(actor, amount='10')
    client = TestClient(create_app())
    token = re.search(r'name="csrf-token" content="([^"]+)"', client.get('/login').text).group(1)
    client.post('/login', data={'email': 'inventory@test.invalid', 'password': 'Supply-Draft-123!', 'consent': 'yes', 'csrf_token': token})
    page = client.get('/portal/inventory/supplies?tab=stock')
    token = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
    form = {'csrf_token': token, 'supply_id': str(gloves), 'movement_type': 'stock_out',
            'quantity': '11', 'reason': 'Packing shift <test> & returns', 'submission_reference': str(uuid4())}
    failed = client.post('/portal/inventory/supplies/movements', data=form)
    assert 'Not enough Gloves' in failed.text
    assert 'modal=stock_out' in str(failed.url)
    assert 'data-inventory-initial-modal="stock_out"' in failed.text
    failed_dialog = supply_dialog(failed.text, 'stock_out')
    assert re.search(r'name="movement_type" value="stock_out"', failed_dialog)
    assert not re.search(r'name="movement_type" value="stock_in"', failed_dialog)
    assert re.search(rf'<option\s+value="{gloves}"[^>]*\sselected', failed_dialog)
    assert 'value="11"' in failed_dialog and re.search(r'Packing shift &lt;test&gt; &amp; returns\s*</textarea\s*>', failed_dialog)
    draft_url = str(failed.url)
    draft_id = re.search(r'name="draft_id"\s+value="([^"]+)"', failed_dialog).group(1)
    assert re.search(r'name="movement_type" value="stock_out"', client.get(draft_url).text)
    # A second browser tab's failed stock-in draft cannot overwrite the first.
    second = client.post('/portal/inventory/supplies/movements', data={**form, 'supply_id': str(first),
        'movement_type': 'stock_in', 'quantity': '0', 'reason': 'Second tab', 'submission_reference': str(uuid4())})
    assert 'data-inventory-initial-modal="stock_in"' in second.text
    assert 'data-inventory-initial-modal="stock_out"' in client.get(draft_url).text
    form.update(quantity='4', draft_id=draft_id, submission_reference=re.search(r'name="submission_reference"\s+value="([^"]+)"', failed_dialog).group(1))
    assert 'Balance updated' in client.post('/portal/inventory/supplies/movements', data=form).text
    assert next(x for x in supplies.supply_choices() if x['supply_id'] == gloves)['quantity_available'] == 6
    assert next(x for x in supplies.supply_choices() if x['supply_id'] == first)['quantity_available'] == 1
    expired = client.get(draft_url).text
    assert 'Packing shift &lt;test&gt;' not in expired
    assert 'saved entry is no longer available' in expired
    assert 'name="movement_type" value="stock_out"' in expired


def test_stock_drafts_do_not_select_another_item_for_invalid_ids(inventory_db, monkeypatch):
    from app import repositories, web_sessions
    from app.portals import shared
    _, actor = inventory_db
    create(actor)
    session = {'csrf_token': 'draft-test'}
    monkeypatch.setattr(web_sessions, '_load_session', lambda *a: dict(session))
    monkeypatch.setattr(web_sessions, '_persist_session', lambda token, data, seconds: session.update(data))
    monkeypatch.setattr(shared, 'require_portal_session', lambda *a: None)
    monkeypatch.setattr(shared, 'session_account_id', lambda *a: actor)
    monkeypatch.setattr(repositories, 'unread_notification_count', lambda *a: 0)
    client = TestClient(create_app())
    for _ in range(7):
        result = client.post('/portal/inventory/supplies/movements', data={'csrf_token': 'draft-test',
            'supply_id': '999999', 'movement_type': 'stock_out', 'quantity': '2', 'reason': 'Invalid item',
            'submission_reference': str(uuid4())})
        assert re.search(r'name="movement_type" value="stock_out"', result.text)
        assert not re.search(r'<option[^>]+ selected', result.text)
    assert len(session['supply_stock_drafts']) == 5


def test_supply_movement_history_pages_transactions_across_items_and_dates(inventory_db, monkeypatch):
    _, actor = inventory_db
    moment = datetime(2026, 1, 1, 15, 59, 59, tzinfo=timezone.utc)
    monkeypatch.setattr(supplies, 'business_now', lambda: moment)
    gloves = create(actor, amount='10')
    create(actor, name='No activity', amount='0')
    moment = datetime(2026, 1, 1, 16, 0, 0, tzinfo=timezone.utc)
    bags = create(actor, name='Packing bags', amount='5')
    move(actor, gloves, amount='2', reason='Issued to packing team')
    move(actor, bags, kind='stock_in', amount='3', reason='Supplier delivery')

    newest = supplies.supply_movements_page(page_size=2)
    assert newest['total'] == 4
    assert [row['reason'] for row in newest['items']] == ['Supplier delivery', 'Issued to packing team']
    assert newest['items'][0]['name'] == 'Packing bags'
    assert (newest['items'][0]['balance_before'], newest['items'][0]['balance_after']) == (5, 8)
    second = supplies.supply_movements_page(page=2, page_size=2)
    assert [row['name'] for row in second['items']] == ['Packing bags', 'Gloves']
    assert not ({row['movement_id'] for row in newest['items']} &
                {row['movement_id'] for row in second['items']})
    assert supplies.supply_movements_page(page=999, page_size=2)['page'] == 2
    assert supplies.supply_movements_page(date(2026, 1, 1))['total'] == 1
    assert supplies.supply_movements_page(date(2026, 1, 2))['total'] == 3
    assert supplies.supply_movements_page(date(2026, 1, 3))['total'] == 0
    assert supplies.supply_movements_page(sort='oldest')['items'][0]['name'] == 'Gloves'
    assert supplies.supply_movements_page(kind='opening')['total'] == 2
    assert supplies.supply_movements_page(kind='stock_in')['total'] == 1
    assert supplies.supply_movements_page(kind='stock_out')['total'] == 1
    assert supplies.supply_movements_page(q='delivery')['total'] == 1
    assert supplies.supply_movements_page(q='Test Inventory')['total'] == 4
    assert supplies.supply_movements_page(q='Packing bags')['total'] == 2
    assert supplies.supply_movements_page(q="' OR true --")['total'] == 0
    assert supplies.supply_movements_page(q='No activity')['total'] == 0
    assert supplies.supply_movements_page(q='Gloves', kind='stock_out')['total'] == 1
