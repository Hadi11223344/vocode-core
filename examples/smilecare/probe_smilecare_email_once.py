#!/usr/bin/env python3
"""Send exactly one probe email via SmileCare email_1 (platform SMTP fallback)."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


async def main() -> int:
    from voice_platform.database import Agent, async_session
    from voice_platform.integrations.executor import WorkflowExecutor
    from voice_platform.integrations.plugins.registry import build_default_plugin_registry

    async with async_session() as session:
        agent = await session.get(Agent, 14)
        node = next(n for n in agent.graph["nodes"] if n["id"] == "email_1")
        tz = ZoneInfo("Asia/Karachi")
        day = datetime.now(tz) + timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
        context = {
            "patient_name": "VOIA Probe Patient",
            "caller_email": "patient.probe@example.com",
            "preferred_dentist": "Dr. Probe",
            "service_requested": "VOIA_PROBE_ONCE_2026-07-21 checkup",
            "preferred_date": day.strftime("%Y-%m-%d"),
            "preferred_time": "11:00",
        }
        ex = WorkflowExecutor(
            session,
            agent.user_id,
            plugin_registry=build_default_plugin_registry(),
            agent_id=agent.id,
            agent_timezone="Asia/Karachi",
        )
        print("Sending ONE email to patient.probe@example.com via email_1...")
        out = await ex._execute_graph_node(node, context)
        print(json.dumps(out, default=str)[:1500])
        ok = out.get("status") == "success"
        nested = out.get("result") if isinstance(out.get("result"), dict) else {}
        if nested.get("success") is False:
            ok = False
        print("RESULT:", "OK" if ok else "FAIL")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
