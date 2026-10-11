"""
One-time migration: update google_calendar integration timezone to Asia/Karachi.

Run inside the app container:
    python scripts/fix_calendar_timezone.py
"""
import asyncio
import json
import sys

sys.path.insert(0, "/app")

from sqlalchemy import select, text
from voice_platform.database import Integration, async_session


async def main():
    async with async_session() as session:
        result = await session.execute(
            select(Integration).where(
                Integration.service_type == "google_calendar",
                Integration.is_active == True,
            )
        )
        integrations = result.scalars().all()
        for integration in integrations:
            config = json.loads(integration.config_json) if integration.config_json else {}
            old_tz = config.get("timezone", "none")
            config["timezone"] = "Asia/Karachi"
            integration.config_json = json.dumps(config)
            print(f"  Integration {integration.id}: timezone {old_tz} -> Asia/Karachi")
        await session.commit()
        print(f"Updated {len(integrations)} google_calendar integration(s)")


if __name__ == "__main__":
    asyncio.run(main())
