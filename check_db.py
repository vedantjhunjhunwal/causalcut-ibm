import asyncio
from app.db.session import Database
from app.core.config import get_settings

async def main():
    db = Database()
    await db.connect()
    try:
        # Get all columns for all tables in public schema
        res = db.client.table("events").select("*").limit(0).execute()
        print("Events columns:")
        print(res.data) # This might just return empty list, we need an RPC to get types or trigger an error on purpose.
        
        # Better: let's try to insert a dummy row with "northstar-alloys-plant-7" and see which column fails
        # Actually, let's just use the Supabase meta api if possible, or execute a raw sql query via RPC? Supabase Python doesn't have raw sql.
    except Exception as e:
        print("Error:", e)

asyncio.run(main())
