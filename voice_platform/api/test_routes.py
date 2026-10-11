"""
Voice Platform — Test Case & Simulation Routes
================================================

CRUD for agent test cases plus single-simulation and batch-test endpoints.
Reuses the playground conversation builder to send messages and evaluate
responses against user-defined success criteria.

Routes:
    GET    /api/agents/{id}/test_cases          — List test cases
    POST   /api/agents/{id}/test_cases          — Create test case
    PUT    /api/agents/{id}/test_cases/{tc_id}   — Update test case
    DELETE /api/agents/{id}/test_cases/{tc_id}   — Delete test case
    POST   /api/agents/{id}/simulate             — Run single simulation
    POST   /api/agents/{id}/batch_test           — Run all test cases
    GET    /api/agents/{id}/test_history         — Recent test runs
"""

import time
from typing import Any, Dict, List, Optional, cast

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.database import Agent, TestCase, TestRun, get_db
from voice_platform.errors import AgentInactiveError, AgentNotFoundError, NotFoundError
from voice_platform.middleware.auth_middleware import get_current_user

router = APIRouter(prefix="/api/agents", tags=["Test Cases"])


# ── Helpers ────────────────────────────────────────────────────────────

async def _fetch_agent(db: AsyncSession, agent_id: int, user_id: int) -> Optional[Agent]:
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        return None
    if agent.user_id != user_id:
        return None
    return agent


def _evaluate_response(
    response: str, criteria_type: str, success_criteria: str
) -> bool:
    """Evaluate agent response against success criteria."""
    response_lower = response.lower()

    if criteria_type == "keyword":
        keywords = [k.strip().lower() for k in success_criteria.split(",") if k.strip()]
        return any(kw in response_lower for kw in keywords)
    elif criteria_type == "contains":
        return success_criteria.lower() in response_lower
    elif criteria_type == "not_contains":
        return success_criteria.lower() not in response_lower
    else:
        return False


# ── Request Models ─────────────────────────────────────────────────────

class TestCaseCreate(BaseModel):
    label: str
    user_prompt: str
    success_criteria: str
    criteria_type: str = "keyword"


class TestCaseUpdate(BaseModel):
    label: Optional[str] = None
    user_prompt: Optional[str] = None
    success_criteria: Optional[str] = None
    criteria_type: Optional[str] = None


class SimulateRequest(BaseModel):
    test_case_id: Optional[int] = None
    user_prompt: Optional[str] = None
    success_criteria: Optional[str] = None
    criteria_type: Optional[str] = None


# ── Test Case CRUD ─────────────────────────────────────────────────────

@router.get("/{agent_id}/test_cases")
async def list_test_cases(
    agent_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await _fetch_agent(db, agent_id, int(cast(Any, user.id)))
    if not agent:
        raise AgentNotFoundError(agent_id)

    result = await db.execute(
        select(TestCase)
        .where(TestCase.agent_id == agent_id, TestCase.user_id == int(cast(Any, user.id)))
        .order_by(TestCase.created_at.desc())
    )
    cases = result.scalars().all()
    return {"test_cases": [tc.to_dict() for tc in cases]}


@router.post("/{agent_id}/test_cases")
async def create_test_case(
    agent_id: int,
    body: TestCaseCreate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await _fetch_agent(db, agent_id, int(cast(Any, user.id)))
    if not agent:
        raise AgentNotFoundError(agent_id)

    if body.criteria_type not in ("keyword", "contains", "not_contains"):
        raise HTTPException(422, "criteria_type must be one of: keyword, contains, not_contains")

    tc = TestCase(
        agent_id=agent_id,
        user_id=int(cast(Any, user.id)),
        label=body.label,
        user_prompt=body.user_prompt,
        success_criteria=body.success_criteria,
        criteria_type=body.criteria_type,
    )
    db.add(tc)
    await db.commit()
    await db.refresh(tc)
    return {"test_case": tc.to_dict()}


@router.put("/{agent_id}/test_cases/{tc_id}")
async def update_test_case(
    agent_id: int,
    tc_id: int,
    body: TestCaseUpdate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await _fetch_agent(db, agent_id, int(cast(Any, user.id)))
    if not agent:
        raise AgentNotFoundError(agent_id)

    result = await db.execute(
        select(TestCase).where(
            TestCase.id == tc_id,
            TestCase.agent_id == agent_id,
            TestCase.user_id == int(cast(Any, user.id)),
        )
    )
    tc = result.scalar_one_or_none()
    if not tc:
        raise NotFoundError(resource="Test case", resource_id=tc_id)

    if body.label is not None:
        tc.label = body.label
    if body.user_prompt is not None:
        tc.user_prompt = body.user_prompt
    if body.success_criteria is not None:
        tc.success_criteria = body.success_criteria
    if body.criteria_type is not None:
        if body.criteria_type not in ("keyword", "contains", "not_contains"):
            raise HTTPException(422, "criteria_type must be one of: keyword, contains, not_contains")
        tc.criteria_type = body.criteria_type

    await db.commit()
    await db.refresh(tc)
    return {"test_case": tc.to_dict()}


@router.delete("/{agent_id}/test_cases/{tc_id}")
async def delete_test_case(
    agent_id: int,
    tc_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await _fetch_agent(db, agent_id, int(cast(Any, user.id)))
    if not agent:
        raise AgentNotFoundError(agent_id)

    result = await db.execute(
        select(TestCase).where(
            TestCase.id == tc_id,
            TestCase.agent_id == agent_id,
            TestCase.user_id == int(cast(Any, user.id)),
        )
    )
    tc = result.scalar_one_or_none()
    if not tc:
        raise NotFoundError(resource="Test case", resource_id=tc_id)

    await db.delete(tc)
    await db.commit()
    return {"deleted": True}


# ── Simulation Endpoints ───────────────────────────────────────────────

async def _run_simulation(
    agent: Agent,
    user_id: int,
    user_prompt: str,
    success_criteria: str,
    criteria_type: str,
    test_case_id: Optional[int],
    db: AsyncSession,
) -> Dict[str, Any]:
    """Run a single simulation and save the result."""
    from voice_platform.api.playground_routes import _build_playground_conversation

    start = time.time()
    conversation = await _build_playground_conversation(agent, user_id)
    msg_result = await conversation.send_message(user_prompt)
    latency_ms = int((time.time() - start) * 1000)

    response_text = msg_result.get("text", "")
    metrics = msg_result.get("metrics", {})
    tokens = metrics.get("tokens", 0)

    passed = _evaluate_response(response_text, criteria_type, success_criteria)

    run = TestRun(
        agent_id=agent.id,
        user_id=user_id,
        test_case_id=test_case_id,
        user_prompt=user_prompt,
        agent_response=response_text,
        passed=passed,
        criteria_type=criteria_type,
        success_criteria=success_criteria,
        latency_ms=latency_ms,
        tokens_used=tokens,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    return {
        "id": run.id,
        "test_case_id": test_case_id,
        "user_prompt": user_prompt,
        "agent_response": response_text,
        "passed": passed,
        "criteria_type": criteria_type,
        "success_criteria": success_criteria,
        "latency_ms": latency_ms,
        "tokens": tokens,
    }


@router.post("/{agent_id}/simulate")
async def run_single_simulation(
    agent_id: int,
    body: SimulateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await _fetch_agent(db, agent_id, int(cast(Any, user.id)))
    if not agent:
        raise AgentNotFoundError(agent_id)
    if not bool(cast(Any, agent.is_active)):
        raise AgentInactiveError(agent_id)

    # Resolve test case if ID provided, otherwise use inline params
    tc = None
    if body.test_case_id:
        result = await db.execute(
            select(TestCase).where(
                TestCase.id == body.test_case_id,
                TestCase.agent_id == agent_id,
                TestCase.user_id == int(cast(Any, user.id)),
            )
        )
        tc = result.scalar_one_or_none()
        if not tc:
            raise NotFoundError(resource="Test case", resource_id=body.test_case_id)

    user_prompt = body.user_prompt or (tc.user_prompt if tc else "")
    success_criteria = body.success_criteria or (tc.success_criteria if tc else "")
    criteria_type = body.criteria_type or (tc.criteria_type if tc else "keyword")
    tc_id = tc.id if tc else None

    if not user_prompt:
        raise HTTPException(422, "user_prompt is required (either inline or from test case)")

    try:
        result = await _run_simulation(
            agent, int(cast(Any, user.id)),
            user_prompt, success_criteria, criteria_type, tc_id, db,
        )
        return {"result": result}
    except Exception as e:
        logger.error(f"Simulation failed for agent {agent_id}: {e}")
        raise HTTPException(500, f"Simulation failed: {str(e)[:200]}")


@router.post("/{agent_id}/batch_test")
async def run_batch_test(
    agent_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await _fetch_agent(db, agent_id, int(cast(Any, user.id)))
    if not agent:
        raise AgentNotFoundError(agent_id)
    if not bool(cast(Any, agent.is_active)):
        raise AgentInactiveError(agent_id)

    result = await db.execute(
        select(TestCase)
        .where(TestCase.agent_id == agent_id, TestCase.user_id == int(cast(Any, user.id)))
        .order_by(TestCase.created_at.asc())
    )
    cases = result.scalars().all()

    if not cases:
        return {"total": 0, "passed": 0, "failed": 0, "results": []}

    results: List[Dict[str, Any]] = []
    for tc in cases:
        try:
            r = await _run_simulation(
                agent, int(cast(Any, user.id)),
                tc.user_prompt, tc.success_criteria, tc.criteria_type, tc.id, db,
            )
            r["label"] = tc.label
            results.append(r)
        except Exception as e:
            logger.warning(f"Test case '{tc.label}' failed: {e}")
            results.append({
                "test_case_id": tc.id,
                "label": tc.label,
                "user_prompt": tc.user_prompt,
                "agent_response": None,
                "passed": False,
                "criteria_type": tc.criteria_type,
                "success_criteria": tc.success_criteria,
                "latency_ms": 0,
                "tokens": 0,
                "error": str(e)[:200],
            })

    passed_count = sum(1 for r in results if r["passed"])
    return {
        "total": len(results),
        "passed": passed_count,
        "failed": len(results) - passed_count,
        "results": results,
    }


@router.get("/{agent_id}/test_history")
async def get_test_history(
    agent_id: int,
    limit: int = 20,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await _fetch_agent(db, agent_id, int(cast(Any, user.id)))
    if not agent:
        raise AgentNotFoundError(agent_id)

    result = await db.execute(
        select(TestRun)
        .where(TestRun.agent_id == agent_id, TestRun.user_id == int(cast(Any, user.id)))
        .order_by(TestRun.created_at.desc())
        .limit(min(limit, 100))
    )
    runs = result.scalars().all()
    return {"test_runs": [run.to_dict() for run in runs]}
