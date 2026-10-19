from __future__ import annotations

from ._shared import *

def _notification_recipient_ids(cur, recipient_role: str | None, recipient_account_id: int | None, category: str) -> list[int]:
    if recipient_account_id is not None:
        cur.execute("SELECT account_id FROM accounts WHERE account_id = %s AND is_active = true;", (recipient_account_id,))
    else:
        cur.execute("SELECT account_id FROM accounts WHERE is_active = true;")
    return [int(row["account_id"]) for row in cur.fetchall()]

def _create_notification_cursor(
    cur,
    *,
    recipient_role: str | None = None,
    recipient_account_id: int | None = None,
    category: str,
    severity: str = "info",
    title: str,
    message: str,
    target_url: str | None = None,
    source_type: str | None = None,
    source_id: int | None = None,
    dedupe_key: str | None = None,
) -> int | None:
    if recipient_role is None and recipient_account_id is None:
        recipient_role = "inventory"
    cur.execute(
        """
        INSERT INTO notifications (
            recipient_role, recipient_account_id, category, severity, title, message,
            target_url, source_type, source_id, dedupe_key
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (dedupe_key) DO UPDATE SET dedupe_key = EXCLUDED.dedupe_key
        RETURNING notification_id;
        """,
        (recipient_role, recipient_account_id, category, severity, title, message,
         target_url, source_type, source_id, dedupe_key),
    )
    notification_id = int(cur.fetchone()["notification_id"])
    recipients = _notification_recipient_ids(cur, recipient_role, recipient_account_id, category)
    for account_id in recipients:
        cur.execute(
            "INSERT INTO notification_recipients (notification_id, account_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
            (notification_id, account_id),
        )
    return notification_id

def create_notification(
    *,
    recipient_role: str | None = None,
    recipient_account_id: int | None = None,
    category: str = "inventory",
    severity: str = "info",
    title: str,
    message: str,
    target_url: str | None = None,
    source_type: str | None = None,
    source_id: int | None = None,
    dedupe_key: str | None = None,
) -> None:
    with get_transaction_cursor() as cur:
        _create_notification_cursor(
            cur, recipient_role=recipient_role or "inventory", recipient_account_id=recipient_account_id,
            category=category, severity=severity, title=title, message=message,
            target_url=target_url, source_type=source_type, source_id=source_id, dedupe_key=dedupe_key,
        )

def list_notifications(role_key: str = "inventory", account_id: int | None = None, limit: int = 8) -> list[dict]:
    return clean_row(fetch_all(
        """
        SELECT n.notification_id, n.category, n.severity, n.title, n.message, n.target_url,
               nr.read_at, n.created_at
        FROM notification_recipients nr
        JOIN notifications n ON n.notification_id = nr.notification_id
        WHERE nr.account_id = %s
        ORDER BY n.created_at DESC, n.notification_id DESC
        LIMIT %s;
        """,
        (account_id, limit),
    ))

def unread_notification_count(role_key: str = "inventory", account_id: int | None = None) -> int:
    row = fetch_one(
        """
        SELECT COUNT(*) AS total
        FROM notification_recipients
        WHERE read_at IS NULL AND account_id = %s;
        """,
        (account_id,),
    )
    return int(row["total"]) if row else 0

def mark_notification_read(account_id: int | None, notification_id: int) -> dict | None:
    if account_id is None:
        return None
    with get_transaction_cursor() as cur:
        cur.execute(
            """
            UPDATE notification_recipients nr
            SET read_at = COALESCE(nr.read_at, now())
            FROM notifications n
            WHERE nr.notification_id = n.notification_id
              AND nr.notification_id = %s
              AND nr.account_id = %s
            RETURNING n.notification_id, n.target_url, n.source_type, n.source_id;
            """,
            (notification_id, account_id),
        )
        row = cur.fetchone()
    return clean_row(row)

def mark_notifications_read(role_key: str = "inventory", account_id: int | None = None) -> None:
    execute_write(
        """
        UPDATE notification_recipients
        SET read_at = now()
        WHERE read_at IS NULL AND account_id = %s;
        """,
        (account_id,),
    )

def list_notification_history(
    account_id: int | None,
    *,
    status: str = "",
    category: str = "",
    page: int = 1,
    page_size: int = 15,
) -> list[dict]:
    offset = (max(page, 1) - 1) * page_size
    return clean_row(fetch_all(
        """
        SELECT n.notification_id, n.category, n.severity, n.title, n.message, n.target_url,
               nr.read_at, n.created_at
        FROM notification_recipients nr
        JOIN notifications n ON n.notification_id = nr.notification_id
        WHERE nr.account_id = %s
          AND (
              %s = ''
              OR (%s = 'unread' AND nr.read_at IS NULL)
              OR (%s = 'read' AND nr.read_at IS NOT NULL)
          )
          AND (%s = '' OR lower(n.category) = lower(%s))
        ORDER BY n.created_at DESC, n.notification_id DESC
        LIMIT %s OFFSET %s;
        """,
        (account_id, status, status, status, category, category, page_size, offset),
    ))

def count_notification_history(
    account_id: int | None,
    *,
    status: str = "",
    category: str = "",
) -> int:
    row = fetch_one(
        """
        SELECT COUNT(*) AS total
        FROM notification_recipients nr
        JOIN notifications n ON n.notification_id = nr.notification_id
        WHERE nr.account_id = %s
          AND (
              %s = ''
              OR (%s = 'unread' AND nr.read_at IS NULL)
              OR (%s = 'read' AND nr.read_at IS NOT NULL)
          )
          AND (%s = '' OR lower(n.category) = lower(%s));
        """,
        (account_id, status, status, status, category, category),
    )
    return int(row["total"]) if row else 0

__all__ = [
    'create_notification',
    'list_notifications',
    'unread_notification_count',
    'mark_notification_read',
    'mark_notifications_read',
    'list_notification_history',
    'count_notification_history',
]
