"""
Voice Platform — Review Queue API Routes
==========================================

Endpoints for human-in-the-loop review of sensitive actions (UC-07).

When a workflow with requires_approval=True triggers an action,
the action is queued for review instead of executing immediately.
These endpoints let administrators review, approve, or reject
pending actions.

Routes:
    GET  /api/reviews           — List pending review items
    GET  /api/reviews/{id}      — Get review item details
    POST /api/reviews/{id}/approve — Approve and execute an action
    POST /api/reviews/{id}/reject  — Reject an action
"""

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.database import ReviewQueue, User, Workflow, get_db
from voice_platform.errors import AppError, NotFoundError, ValidationError
from voice_platform.middleware.auth_middleware import get_current_user

# Create router
router = APIRouter(prefix="/api/reviews", tags=["Reviews"])


def _safe_json_loads(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


# ── Request Schemas ────────────────────────────────────────────────────

class ReviewDecisionRequest(BaseModel):
    """Request body for approving or rejecting a review item."""
    notes: Optional[str] = None  # Optional reviewer notes


# ── Routes ─────────────────────────────────────────────────────────────

@router.get("")
async def list_reviews(
    status: Optional[str] = Query(default="pending", description="Filter by status"),
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=20, ge=1, le=100, description="Items per page"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List review queue items with optional filtering.
    
    Returns items sorted by creation date (newest first).
    Only shows items belonging to the authenticated user.
    
    Args:
        status: Filter by status ('pending', 'approved', 'rejected', or None for all)
        page: Page number
        per_page: Items per page
        user: Authenticated user
        db: Database session
        
    Returns:
        Paginated list of review items with count
    """
    # Build base query scoped to user
    query = select(ReviewQueue).where(ReviewQueue.user_id == user.id)
    count_query = select(func.count(ReviewQueue.id)).where(ReviewQueue.user_id == user.id)
    
    # Apply optional status filter
    if status is not None:
        query = query.where(ReviewQueue.status == status)
        count_query = count_query.where(ReviewQueue.status == status)
    
    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # Apply pagination
    offset = (page - 1) * per_page
    query = query.order_by(ReviewQueue.created_at.desc()).offset(offset).limit(per_page)
    
    result = await db.execute(query)
    items = result.scalars().all()
    
    return {
        "reviews": [item.to_dict() for item in items],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.get("/{review_id}")
async def get_review(
    review_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get details of a specific review item.
    
    Only returns the item if it belongs to the current user.
    """
    result = await db.execute(
        select(ReviewQueue).where(
            ReviewQueue.id == review_id,
            ReviewQueue.user_id == user.id,
        )
    )
    item = result.scalar_one_or_none()
    
    if item is None:
        raise NotFoundError(resource="Review item", resource_id=review_id)
    
    return {"review": item.to_dict()}


@router.post("/{review_id}/approve")
async def approve_review(
    review_id: int,
    request: ReviewDecisionRequest = ReviewDecisionRequest(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Approve a pending action for execution.
    
    Changes the review status to 'approved' and triggers
    the action execution (webhook call to action_url).
    
    Args:
        review_id: ID of the review item
        request: Optional reviewer notes
        user: Authenticated user
        db: Database session
    """
    result = await db.execute(
        select(ReviewQueue).where(
            ReviewQueue.id == review_id,
            ReviewQueue.user_id == user.id,
        )
    )
    item = result.scalar_one_or_none()
    
    if item is None:
        raise NotFoundError(resource="Review item", resource_id=review_id)
    
    if item.status != "pending":
        raise ValidationError(
            field="status",
            message=f"Item already {item.status}.",
            suggestion="Only pending review items can be approved or rejected.",
        )
    
    # Execute the action and report result
    execution_result = {"success": True, "message": "No executable action configured"}
    if item.action_type == "workflow_execution":
        try:
            from voice_platform.integrations.executor import WorkflowExecutor

            params = _safe_json_loads(item.action_params, {})
            if not isinstance(params, dict):
                params = {}

            workflow_id = params.get("workflow_id") or item.workflow_id
            steps = params.get("steps")
            graph = params.get("graph")
            context = params.get("context") or {}
            if not isinstance(context, dict):
                context = {}

            steps = _safe_json_loads(steps, steps)
            graph = _safe_json_loads(graph, graph)
            if steps is not None and not isinstance(steps, list):
                steps = []
            if graph is not None and not isinstance(graph, dict):
                graph = None

            if (not steps and not graph) and workflow_id:
                wf_result = await db.execute(
                    select(Workflow).where(
                        Workflow.id == workflow_id,
                        Workflow.user_id == user.id,
                    )
                )
                workflow = wf_result.scalar_one_or_none()
                if workflow:
                    if workflow.steps_json:
                        loaded_steps = _safe_json_loads(workflow.steps_json, [])
                        steps = loaded_steps if isinstance(loaded_steps, list) else []
                    if workflow.graph_json:
                        loaded_graph = _safe_json_loads(workflow.graph_json, None)
                        graph = loaded_graph if isinstance(loaded_graph, dict) else None

            if not steps and not graph:
                execution_result = {
                    "success": False,
                    "error": "No workflow definition available for execution",
                }
            else:
                from voice_platform.integrations.plugins.registry import (
                    build_default_plugin_registry,
                )
                executor = WorkflowExecutor(db, user.id, plugin_registry=build_default_plugin_registry())
                execution = await executor.execute_workflow(
                    steps=steps,
                    graph=graph,
                    context=context,
                )
                results = execution.get("results", [])
                execution_result = {
                    "success": all(r.get("status") == "success" for r in results),
                    "mode": execution.get("mode", "steps"),
                    "steps_executed": len(results),
                    "results": results,
                }
        except Exception as e:
            from loguru import logger
            logger.error(f"Action execution failed after approval: {e}")
            execution_result = {"success": False, "error": str(e)}
    elif item.action_url:
        try:
            from voice_platform.actions.action_executor import execute_action
            raw = await execute_action(
                action_url=item.action_url,
                action_type=item.action_type,
                params=item.action_params,
            )
            # Ensure serializable result
            execution_result = raw if isinstance(raw, dict) else {"success": True}
        except Exception as e:
            from loguru import logger
            logger.error(f"Action execution failed after approval: {e}")
            execution_result = {"success": False, "error": str(e)}

    if execution_result.get("success"):
        item.status = "approved"
        item.reviewed_by = user.id
        item.reviewed_at = datetime.now(timezone.utc)
        item.review_notes = request.notes
        await db.commit()
        await db.refresh(item)
        message = "Action approved and executed"
    else:
        message = "Execution failed; review remains pending"
    
    return {
        "review": item.to_dict(),
        "message": message,
        "execution": execution_result,
    }


@router.post("/{review_id}/reject")
async def reject_review(
    review_id: int,
    request: ReviewDecisionRequest = ReviewDecisionRequest(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Reject a pending action.
    
    Changes the review status to 'rejected'. The action
    will not be executed.
    """
    result = await db.execute(
        select(ReviewQueue).where(
            ReviewQueue.id == review_id,
            ReviewQueue.user_id == user.id,
        )
    )
    item = result.scalar_one_or_none()
    
    if item is None:
        raise NotFoundError(resource="Review item", resource_id=review_id)
    
    if item.status != "pending":
        raise ValidationError(
            field="status",
            message=f"Item already {item.status}.",
            suggestion="Only pending review items can be approved or rejected.",
        )
    
    # Update status
    item.status = "rejected"
    item.reviewed_by = user.id
    item.reviewed_at = datetime.now(timezone.utc)
    item.review_notes = request.notes
    
    await db.commit()
    await db.refresh(item)
    
    return {
        "review": item.to_dict(),
        "message": "Action rejected",
    }
