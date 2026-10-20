from __future__ import annotations

from ._shared import *

def role_key_for_account_type(account_type: str, team_leader_role: str | None = None) -> str | None:
    if account_type == "owner" or (account_type == "team_leader" and team_leader_role == "inventory"):
        return "inventory"
    return None

def authenticate_account(email: str, password: str) -> dict | None:
    account = fetch_one(
        """
        SELECT account_id, account_type, team_leader_role, name, email, password_hash,
               profile_image_path, profile_image_position_x, profile_image_position_y, profile_image_scale,
               is_active, activation_status
        FROM accounts
        WHERE lower(email) = lower(%s)
        LIMIT 1;
        """,
        (email.strip(),),
    )
    if (account is None or not account["is_active"] or account["activation_status"] != "active"
            or role_key_for_account_type(account["account_type"], account["team_leader_role"]) is None):
        return None

    if not verify_password(password, account["password_hash"]):
        return None

    if password_needs_rehash(account["password_hash"]):
        execute_write(
            "UPDATE accounts SET password_hash = %s WHERE account_id = %s;",
            (hash_password(password), account["account_id"]),
        )

    clean = clean_row(account)
    clean["role_key"] = "inventory"
    clean["team_leader_role"] = "inventory"
    return clean

def account_portal_profile(account_id: int) -> dict | None:
    account = fetch_one("""
        SELECT account_id, account_type, team_leader_role, name, email,
               profile_image_path, profile_image_position_x, profile_image_position_y, profile_image_scale,
               is_active, activation_status
        FROM accounts
        WHERE account_id = %s
        LIMIT 1;
    """, (account_id,))
    if (not account or not account["is_active"] or account["activation_status"] != "active"
            or role_key_for_account_type(account["account_type"], account["team_leader_role"]) is None):
        return None
    clean = clean_row(account)
    clean["role_key"] = "inventory"
    clean["team_leader_role"] = "inventory"
    return clean

def active_session_account(account_id: int) -> dict | None:
    return account_portal_profile(account_id)

def update_account_profile_image(
    account_id: int,
    profile_image_path: str | None,
    position_x: object = 50,
    position_y: object = 50,
    scale: object = 1,
) -> dict:
    cleaned_path = profile_image_path.strip() if profile_image_path else None
    if cleaned_path and not cleaned_path.startswith("uploads/profiles/"):
        raise ValueError("Profile image path is invalid.")
    clean_x = max(0, min(100, float(position_x or 50)))
    clean_y = max(0, min(100, float(position_y or 50)))
    clean_scale = max(1, min(2, float(scale or 1)))
    account = execute_write(
        """
        UPDATE accounts
        SET profile_image_path = %s,
            profile_image_position_x = %s,
            profile_image_position_y = %s,
            profile_image_scale = %s
        WHERE account_id = %s
          AND is_active = true
          AND activation_status = 'active'
        RETURNING account_id, account_type, team_leader_role, name, email,
                  profile_image_path, profile_image_position_x, profile_image_position_y, profile_image_scale,
                  is_active, activation_status;
        """,
        (cleaned_path, clean_x, clean_y, clean_scale, account_id),
        returning=True,
    )
    if not account:
        raise ValueError("Account was not found.")
    clean = clean_row(account)
    clean["role_key"] = "inventory"
    clean["team_leader_role"] = "inventory"
    add_log(clean["name"], "updated_profile_picture", "Account profile", actor_account_id=account_id)
    return clean

def change_account_password_direct(account_id: int, current_password: str, new_password: str) -> None:
    account = fetch_one(
        """
        SELECT account_id, name, password_hash
        FROM accounts
        WHERE account_id = %s
          AND is_active = true
        LIMIT 1;
        """,
        (account_id,),
    )
    if not account:
        raise ValueError("Account was not found.")
    if not verify_password(current_password, account["password_hash"]):
        raise ValueError("Current password is incorrect.")
    cleaned_password = validate_password_policy(new_password)
    execute_write(
        "UPDATE accounts SET password_hash = %s WHERE account_id = %s;",
        (hash_password(cleaned_password), account_id),
    )
    add_log(account["name"], "changed_password", "Account profile", actor_account_id=account_id)

def record_user_consent(account_id: int, policy_version: str, consent_source: str, provider: str | None = None) -> None:
    execute_write(
        """
        INSERT INTO user_consents (account_id, policy_version, consent_source, provider)
        VALUES (%s, %s, %s, %s);
        """,
        (account_id, policy_version, consent_source, provider),
    )

def count_accounts(q: str = "", account_type: str = "", account_types: tuple[str, ...] | None = None) -> int:
    row = fetch_one("SELECT COUNT(*) AS total FROM accounts WHERE is_active = true;")
    return int(row["total"]) if row else 0

__all__ = [
    "account_portal_profile",
    "active_session_account",
    "authenticate_account",
    "change_account_password_direct",
    "count_accounts",
    "record_user_consent",
    "role_key_for_account_type",
    "update_account_profile_image",
]
