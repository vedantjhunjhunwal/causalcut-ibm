"""Create the missing worker_zone_history table via Supabase Management API.

Since psycopg2 points to a different venv, use the Supabase REST SQL endpoint
instead (via the service_role key).

Run: python scripts/migrate_worker_zone_history.py
"""
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

SQL = """
CREATE TABLE IF NOT EXISTS worker_zone_history (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    worker_id       TEXT NOT NULL,
    zone_id         TEXT,
    event_time      TIMESTAMPTZ NOT NULL,
    event_id        UUID NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_wzh_worker
    ON worker_zone_history (worker_id, event_time DESC);

NOTIFY pgrst, 'reload schema';
"""

# Try psycopg2 first (direct SQL), fall back to Supabase RPC
try:
    import psycopg2
    if DATABASE_URL:
        print("Using direct PostgreSQL connection...")
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(SQL)
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'worker_zone_history'
            ORDER BY ordinal_position;
        """)
        cols = cur.fetchall()
        print(f"\n✅ worker_zone_history created with {len(cols)} columns:")
        for name, dtype in cols:
            print(f"   • {name} ({dtype})")
        cur.close()
        conn.close()
        print("\n✅ Done!")
        exit(0)
except ImportError:
    print("psycopg2 not available, trying Supabase REST RPC...")
except Exception as e:
    print(f"psycopg2 failed: {e}, trying Supabase REST RPC...")

# Fallback: use Supabase REST rpc endpoint
if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    print("ERROR: Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env")
    exit(1)

print(f"Connecting to {SUPABASE_URL}...")

# Try the pg_net or raw SQL RPC if available.
# Supabase exposes a /rest/v1/rpc/ endpoint for stored procedures.
# We can create the table by calling the management SQL API at /sql
# However that requires the management API. Let's try the simpler approach:
# POST to the Supabase Management API or use the pg_query RPC.

# Actually, for Supabase cloud we can use the DB URL directly with httpx + SQL.
# The simplest approach: parse DATABASE_URL and use it with pg8000 (pure Python).

try:
    import pg8000.native
    print("Using pg8000 (pure Python PostgreSQL driver)...")
    
    # Parse DATABASE_URL: postgresql://user:pass@host:port/dbname
    from urllib.parse import urlparse
    parsed = urlparse(DATABASE_URL)
    
    conn = pg8000.native.Connection(
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=parsed.port or 5432,
        database=parsed.path.lstrip('/'),
        ssl_context=True,
    )
    
    for stmt in SQL.strip().split(';'):
        stmt = stmt.strip()
        if stmt:
            conn.run(stmt)
    
    rows = conn.run("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'worker_zone_history'
        ORDER BY ordinal_position
    """)
    print(f"\n✅ worker_zone_history created with {len(rows)} columns:")
    for name, dtype in rows:
        print(f"   • {name} ({dtype})")
    conn.close()
    print("\n✅ Done!")

except ImportError:
    print("\nERROR: Neither psycopg2 nor pg8000 available.")
    print("Install one of them:")
    print("  pip install psycopg2-binary")
    print("  pip install pg8000")
    print("\nOr run this SQL manually in the Supabase SQL Editor:")
    print(SQL)
    exit(1)
