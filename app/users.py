"""
Allowlist-based identity. Only the two emails in Config.email_role_map() may
ever get a session — anyone else's Google sign-in is rejected before a user
row or session is created.
"""
from flask_login import UserMixin


class User(UserMixin):
    def __init__(self, id: int, email: str, role: str):
        self.id = str(id)
        self.email = email
        self.role = role

    def get_id(self) -> str:
        return self.id


def resolve_role_for_email(email: str, email_role_map: dict) -> str | None:
    """Returns 'owner' / 'member', or None if the email isn't allowlisted."""
    return email_role_map.get(email.strip().lower())


def upsert_user(conn, google_sub: str, email: str, role: str) -> User:
    """Create or update the local user row for an allowlisted sign-in.
    Role is always re-derived from the allowlist on login (passed in by the
    caller) — never read back from a client-controlled value."""
    email = email.strip().lower()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (google_sub, email, role)
            VALUES (%s, %s, %s)
            ON CONFLICT (google_sub) DO UPDATE SET email = EXCLUDED.email, role = EXCLUDED.role
            RETURNING id, email, role
            """,
            (google_sub, email, role),
        )
        row = cur.fetchone()
    conn.commit()
    return User(id=row[0], email=row[1], role=row[2])


def load_user_by_id(conn, user_id: str) -> User | None:
    with conn.cursor() as cur:
        cur.execute("SELECT id, email, role FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
    return User(id=row[0], email=row[1], role=row[2]) if row else None
