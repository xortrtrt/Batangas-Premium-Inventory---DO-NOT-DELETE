"""Independent supplies stock, with an immutable movement ledger."""
from datetime import datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from hashlib import sha256

from app.business_time import BUSINESS_ZONE, business_now
from app.inventory_measurements import parse_decimal_exact
from app.uploads import validate_product_image
from .._shared import clean_row, fetch_all, get_transaction_cursor
from .movements import _inventory_actor_name

SUPPLY_UNITS = (('piece', 'Pieces'), ('pair', 'Pairs'), ('box', 'Boxes'),
                ('roll', 'Rolls'), ('pack', 'Packs'), ('meter', 'Meters'))
MAX_QUANTITY = Decimal('999999999.999')


def validate_supply_image(content_type, content):
    try:
        validate_product_image(content_type, content)
    except ValueError as exc:
        raise ValueError(str(exc).replace('Product image', 'Supply image')) from None


def _save_image(cur, supply_id, image):
    cur.execute('''INSERT INTO inventory_supply_images(supply_id,content_type,image_data) VALUES (%s,%s,%s)
        ON CONFLICT (supply_id) DO UPDATE SET content_type=EXCLUDED.content_type,image_data=EXCLUDED.image_data''',
        (supply_id, *image))


def save_supply_image(supply_id, image, actor_id):
    validate_supply_image(*image)
    with get_transaction_cursor() as cur:
        _actor(cur, actor_id)
        cur.execute('SELECT supply_id FROM inventory_supply_items WHERE supply_id=%s FOR UPDATE', (supply_id,))
        if cur.fetchone() is None:
            raise ValueError('Choose a valid supply item.')
        _save_image(cur, supply_id, image)


def _text(value, label, limit):
    value = ' '.join(str(value).split())
    if not value or len(value) > limit:
        raise ValueError(f'{label} must be 1 to {limit} characters.')
    return value


def _reference(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Invalid submission reference. Reload and try again.') from None


def _quantity(value, unit, *, opening=False):
    if unit not in dict(SUPPLY_UNITS):
        raise ValueError('Choose a valid supply unit.')
    value = str(value).strip()
    if len(value) > 13:
        raise ValueError('Quantity exceeds the supported stock limit.')
    result = parse_decimal_exact(value, 'Quantity', scale=3, nonnegative=opening, positive=not opening)
    if result > MAX_QUANTITY:
        raise ValueError('Quantity exceeds the supported stock limit.')
    if unit != 'meter' and result != result.to_integral_value():
        raise ValueError('This counting unit requires a whole quantity.')
    return result


def _actor(cur, actor_id):
    if actor_id is None:
        raise ValueError('Sign in before recording supplies stock.')
    return _inventory_actor_name(cur, actor_id)


def _insert_movement(cur, item, kind, amount, reason, reference, actor_id, actor_name, timestamp):
    before = item['quantity_available']
    delta = -amount if kind == 'stock_out' else amount
    after = before + delta
    if after < 0:
        raise ValueError(f"Not enough {item['name']}. Available: {before:g} {item['unit']}.")
    if after > MAX_QUANTITY:
        raise ValueError('The resulting balance exceeds the supported stock limit.')
    cur.execute('UPDATE inventory_supply_items SET quantity_available=%s WHERE supply_id=%s', (after, item['supply_id']))
    cur.execute('''INSERT INTO inventory_supply_movements
        (supply_id,submission_reference,movement_type,quantity_delta,unit,balance_before,balance_after,
         actor_account_id,actor_name,reason,created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
        (item['supply_id'], reference, kind, delta, item['unit'], before, after, actor_id, actor_name, reason, timestamp))


def create_supply(name, category, unit, initial_quantity, reference, actor_id, *, image=None):
    if image is not None:
        validate_supply_image(*image)
    image_hash = sha256(image[1]).hexdigest() if image is not None else None
    name, category = _text(name, 'Item name', 120), _text(category, 'Category', 80)
    amount = _quantity(initial_quantity, unit, opening=True)
    reference = _reference(reference)
    with get_transaction_cursor() as cur:
        actor_name = _actor(cur, actor_id)
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f'supply-create:{reference}',))
        cur.execute('SELECT * FROM inventory_supply_items WHERE creation_reference=%s', (reference,))
        existing = cur.fetchone()
        if existing:
            if (existing['name'], existing['category'], existing['unit'], existing['initial_quantity'], existing['created_by_account_id'], existing['creation_image_sha256']) != (name, category, unit, amount, actor_id, image_hash):
                raise ValueError('This reference was used for different item details. Reload and try again.')
            return {'supply_id': existing['supply_id'], 'already_recorded': True}
        timestamp = business_now()
        cur.execute('''INSERT INTO inventory_supply_items
            (name,category,unit,initial_quantity,creation_reference,created_by_account_id,created_at,creation_image_sha256)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (lower(name)) DO NOTHING RETURNING *''',
            (name, category, unit, amount, reference, actor_id, timestamp, image_hash))
        item = cur.fetchone()
        if item is None:
            raise ValueError('A supply item with this name already exists. Use a different name for each size or variant.')
        if image is not None:
            _save_image(cur, item['supply_id'], image)
        if amount:
            _insert_movement(cur, item, 'opening', amount, 'Opening stock', reference, actor_id, actor_name, timestamp)
    return {'supply_id': item['supply_id'], 'already_recorded': False}


def record_supply_movement(supply_id, kind, quantity, reason, reference, actor_id):
    if not isinstance(supply_id, int) or not 0 < supply_id <= 9223372036854775807:
        raise ValueError('Choose a valid supply item.')
    if kind not in {'stock_in', 'stock_out'}:
        raise ValueError('Choose Stock in or Stock out.')
    reason, reference = _text(reason, 'Reason', 500), _reference(reference)
    with get_transaction_cursor() as cur:
        actor_name = _actor(cur, actor_id)
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f'supply-movement:{reference}',))
        cur.execute('SELECT * FROM inventory_supply_movements WHERE submission_reference=%s', (reference,))
        existing = cur.fetchone()
        if existing:
            amount = _quantity(quantity, existing['unit'])
            delta = -amount if kind == 'stock_out' else amount
            if (existing['supply_id'], existing['movement_type'], existing['quantity_delta'], existing['reason'], existing['actor_account_id']) != (supply_id, kind, delta, reason, actor_id):
                raise ValueError('This reference was used for different movement details. Reload and try again.')
            return {'already_recorded': True}
        cur.execute('SELECT * FROM inventory_supply_items WHERE supply_id=%s FOR UPDATE', (supply_id,))
        item = cur.fetchone()
        if item is None:
            raise ValueError('Choose a valid supply item.')
        amount = _quantity(quantity, item['unit'])
        _insert_movement(cur, item, kind, amount, reason, reference, actor_id, actor_name, business_now())
    return {'already_recorded': False}


def supply_choices():
    return clean_row(fetch_all('''SELECT supply_id,name,unit,quantity_available,
        EXISTS(SELECT 1 FROM inventory_supply_images i WHERE i.supply_id=s.supply_id) has_image
        FROM inventory_supply_items s ORDER BY lower(name),supply_id'''))


def supply_movements_page(day=None, q='', kind='', sort='', page=1, page_size=12):
    """Page individual transactions across all items; dates use Manila boundaries."""
    conditions, params = [], []
    if day is not None:
        start = datetime.combine(day, time.min, BUSINESS_ZONE)
        conditions.append('m.created_at >= %s AND m.created_at < %s')
        params.extend((start, start + timedelta(days=1)))
    if kind in {'opening', 'stock_in', 'stock_out'}:
        conditions.append('m.movement_type = %s')
        params.append(kind)
    if q.strip():
        conditions.append('''(s.name ILIKE %s OR s.category ILIKE %s OR m.actor_name ILIKE %s
            OR m.reason ILIKE %s OR replace(m.movement_type, '_', ' ') ILIKE %s)''')
        params.extend([f'%{q.strip()}%'] * 5)
    where = 'WHERE ' + ' AND '.join(conditions) if conditions else ''
    order = {'oldest': 'm.created_at ASC, m.movement_id ASC',
             'actor_asc': 'lower(m.actor_name), m.created_at DESC, m.movement_id DESC'}.get(
                 sort, 'm.created_at DESC, m.movement_id DESC')
    source = 'FROM inventory_supply_movements m JOIN inventory_supply_items s ON s.supply_id=m.supply_id'
    with get_transaction_cursor() as cur:
        cur.execute(f'SELECT count(*) total {source} {where}', params)
        total = cur.fetchone()['total']
        page = min(max(1, page), max(1, (total + page_size - 1) // page_size))
        cur.execute(f'''SELECT m.*, s.name, s.category {source} {where}
            ORDER BY {order} LIMIT %s OFFSET %s''', [*params, page_size, (page - 1) * page_size])
        items = cur.fetchall()
    return clean_row({'items': items, 'total': total, 'page': page})


def supplies_page(day, q='', page=1, page_size=12):
    """Summaries and children use Manila day boundaries and a single query snapshot."""
    start = datetime.combine(day, time.min, BUSINESS_ZONE)
    end = start + timedelta(days=1)
    search = f'%{q.strip()}%'
    with get_transaction_cursor() as cur:
        cur.execute('''SELECT count(*) total FROM inventory_supply_items
            WHERE created_at<%s AND (name ILIKE %s OR category ILIKE %s)''', (end, search, search))
        total = cur.fetchone()['total']
        page = min(max(1, page), max(1, (total+page_size-1)//page_size))
        cur.execute('''SELECT s.*,
            EXISTS(SELECT 1 FROM inventory_supply_images i WHERE i.supply_id=s.supply_id) has_image,
            COALESCE(m.opening,0) opening_balance,COALESCE(m.stock_in,0) stock_in,
            COALESCE(m.stock_out,0) stock_out,COALESCE(m.closing,0) closing_balance,
            COALESCE((SELECT json_agg(json_build_object(
                'movement_type',h.movement_type,'quantity_delta',h.quantity_delta,
                'unit',h.unit,'balance_before',h.balance_before,'balance_after',h.balance_after,
                'actor_name',h.actor_name,'reason',h.reason,'created_at',h.created_at)
                ORDER BY h.created_at,h.movement_id) FROM inventory_supply_movements h
                WHERE h.supply_id=s.supply_id AND h.created_at>=%s AND h.created_at<%s),'[]'::json) movements
            FROM inventory_supply_items s LEFT JOIN LATERAL (
                SELECT SUM(quantity_delta) FILTER (WHERE created_at<%s) opening,
                    SUM(quantity_delta) FILTER (WHERE created_at>=%s AND quantity_delta>0) stock_in,
                    -SUM(quantity_delta) FILTER (WHERE created_at>=%s AND quantity_delta<0) stock_out,
                    SUM(quantity_delta) closing
                FROM inventory_supply_movements WHERE supply_id=s.supply_id AND created_at<%s
            ) m ON true WHERE s.created_at<%s AND (s.name ILIKE %s OR s.category ILIKE %s)
            ORDER BY lower(s.name),s.supply_id LIMIT %s OFFSET %s''',
            (start, end, start, start, start, end, end, search, search, page_size, (page-1)*page_size))
        items = cur.fetchall()
        for item in items:
            for movement in item['movements']:
                movement['created_at'] = datetime.fromisoformat(movement['created_at'])
    return clean_row({'items': items, 'total': total, 'page': page})
