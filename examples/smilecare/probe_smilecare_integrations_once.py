#!/usr/bin/env python3
"""One careful probe of SmileCare booking integrations (Calendar + Sheets + Email).

Runs exactly once per service through WorkflowExecutor._execute_graph_node —
the same path telephony/playground use. Tagged VOIA_PROBE_ONCE so entries
are easy to find/delete. Does not place phone calls.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


PROBE_TAG = "VOIA_PROBE_ONCE_2026-07-21"


async def main() -> int:
    from voice_platform.database import Agent, async_session
    from voice_platform.integrations.executor import WorkflowExecutor
    from voice_platform.integrations.plugins.registry import build_default_plugin_registry

    async with async_session() as session:
        agent = await session.get(Agent, 14)
        if agent is None:
            print("FAIL: agent 14 missing")
            return 1

        graph = agent.graph or {}
        nodes_by_id = {n["id"]: n for n in graph.get("nodes", [])}
        for need in ("action_3", "sheets_1", "email_1"):
            if need not in nodes_by_id:
                print(f"FAIL: missing node {need}")
                return 1

        print(f"USER={agent.user_id} AGENT={agent.id} {agent.name}")
        print(f"PROBE_TAG={PROBE_TAG}")
        print("Target email: patient.probe@example.com")
        print("Account note: DB owner is owner@example.com (user 1)")

        tz = ZoneInfo("Asia/Karachi")
        # Next weekday at 11:00 PKT — avoids weekend/business-hour surprises
        day = datetime.now(tz) + timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
        day = day.replace(hour=11, minute=0, second=0, microsecond=0)
        preferred_date = day.strftime("%Y-%m-%d")
        preferred_time = "11:00"

        context = {
            "patient_name": "VOIA Probe Patient",
            "caller_phone": "+10000000000",
            "caller_email": "patient.probe@example.com",
            "preferred_dentist": "Dr. Probe",
            "service_requested": f"{PROBE_TAG} checkup",
            "is_new_patient": "new",
            "preferred_date": preferred_date,
            "preferred_time": preferred_time,
            "current_date": datetime.now(tz).strftime("%Y-%m-%d"),
            "insurance_provider": "",
            "visit_type": "appointment",
            "is_emergency": "false",
            "confirm_booking": "true",
        }
        print(f"Slot: {preferred_date} {preferred_time} Asia/Karachi")

        executor = WorkflowExecutor(
            session,
            agent.user_id,
            plugin_registry=build_default_plugin_registry(),
            agent_id=agent.id,
            agent_timezone="Asia/Karachi",
        )

        results = {}
        order = [
            ("calendar", "action_3"),
            ("sheets", "sheets_1"),
            ("email", "email_1"),
        ]
        for name, node_id in order:
            node = nodes_by_id[node_id]
            print(f"\n=== {name.upper()} via {node_id} (once) ===")
            try:
                out = await executor._execute_graph_node(node, dict(context))
            except Exception as exc:
                out = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            results[name] = out
            # Compact safe print
            compact = {
                "status": out.get("status"),
                "error": out.get("error"),
                "success": (out.get("result") or {}).get("success")
                if isinstance(out.get("result"), dict)
                else None,
            }
            raw = out.get("result") if isinstance(out.get("result"), dict) else {}
            for k in (
                "event_id",
                "event_created",
                "html_link",
                "updated_range",
                "updated_rows",
                "row_appended",
                "message_id",
                "email_sent",
                "to",
                "error",
            ):
                if k in raw:
                    compact[k] = raw[k]
            print(json.dumps(compact, default=str)[:1000])

        print("\n=== SUMMARY ===")
        failed = []
        for name, out in results.items():
            ok = out.get("status") == "success"
            # some plugins nest success
            nested = out.get("result") if isinstance(out.get("result"), dict) else {}
            if nested and nested.get("success") is False:
                ok = False
            print(f"{name}: {'OK' if ok else 'FAIL'} {out.get('error') or nested.get('error') or ''}")
            if not ok:
                failed.append(name)
        return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
