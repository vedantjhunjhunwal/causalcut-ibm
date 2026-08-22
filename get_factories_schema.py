import asyncio
from app.db.session import Database
from app.core.config import get_settings

async def main():
    db = Database()
    await db.connect()
    try:
        # Fetch a single row to see columns, or just try to insert one
        res = db.client.table("factories").select("*").limit(1).execute()
        print("Factories columns / sample:")
        print(res.data)
        
        # Try to insert target uuid 1
        target1 = "00000000-0000-0000-0000-000000000001"
        target2 = "00000000-0000-0000-0000-000000000002"
        
        db.client.table("factories").upsert({"factory_id": target1, "name": "Steelforge Dummy"}).execute()
        db.client.table("factories").upsert({"factory_id": target2, "name": "Northstar Dummy"}).execute()
        print("Inserted dummy factories")
    except Exception as e:
        print("Error:", e)

asyncio.run(main())
