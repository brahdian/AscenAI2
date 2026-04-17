"""Flows API — CRUD for workflow definitions and execution management.

Endpoints
---------
POST   /{agent_id}/workflows                            Create workflow
GET    /{agent_id}/workflows                            List workflows
GET    /{agent_id}/workflows/{flow_id}                  Get workflow definition
PUT    /{agent_id}/workflows/{flow_id}                  Update workflow (bumps version)
DELETE /{agent_id}/workflows/{flow_id}                  Deactivate workflow
POST   /{agent_id}/workflows/{flow_id}/activate         Activate → register as MCP tool
POST   /{agent_id}/workflows/{flow_id}/deactivate       Deactivate → deregister tool
GET    /{agent_id}/workflows/{flow_id}/executions/{session_id}  Get execution state
POST   /{agent_id}/workflows/{flow_id}/advance          Advance execution (testing)

All routes are mounted under /api/v1/agents by main.py, so full paths are:
  POST /api/v1/agents/{agent_id}/workflows
  ...
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.agent import Agent
from app.models.workflow import Workflow, WorkflowExecution
from app.schemas.workflow import (
    WorkflowAdvanceRequest,
    WorkflowAdvanceResult,
    WorkflowCreate,
    WorkflowExecutionResponse,
    WorkflowResponse,
    WorkflowUpdate,
)
from app.services.workflow_engine import WorkflowEngine, ExecutionNotFoundError, WorkflowNotFoundError
from app.services.workflow_registry import WorkflowRegistry

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["workflows"])


def _tenant_id(request: Request) -> str:
    tid = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    return tid


async def _get_db_session(tenant_id: str) -> AsyncSession:
    """Helper to yield a tenant-scoped DB session inside endpoint logic."""
    from app.core.database import AsyncSessionLocal
    from sqlalchemy import text
    session = AsyncSessionLocal()
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )
    return session


async def _get_agent_or_404(db: AsyncSession, agent_id: uuid.UUID, tenant_id: uuid.UUID) -> Agent:
    agent = await db.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.tenant_id == tenant_id,
        )
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")
    return agent


async def _get_workflow_or_404(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    agent_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> Workflow:
    wf = await db.scalar(
        select(Workflow).where(
            Workflow.id == workflow_id,
            Workflow.agent_id == agent_id,
            Workflow.tenant_id == tenant_id,
        )
    )
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return wf


# ---------------------------------------------------------------------------
# Create workflow
# ---------------------------------------------------------------------------

@router.post("/{agent_id}/workflows", response_model=WorkflowResponse, status_code=201)
async def create_workflow(
    agent_id: uuid.UUID,
    body: WorkflowCreate,
    request: Request,
):
    tid_str = _tenant_id(request)
    tid = uuid.UUID(tid_str)
    
    # Validate cron expression if trigger_type is cron
    if body.trigger_type == "cron":
        from croniter import croniter, CroniterBadCronError
        schedule = body.trigger_config.get("schedule", "")
        if not schedule:
            raise HTTPException(status_code=422, detail="Cron schedule is required for cron trigger type")
        try:
            croniter(schedule)
        except CroniterBadCronError:
            raise HTTPException(status_code=422, detail=f"Invalid cron expression: {schedule}")

    db = await _get_db_session(tid_str)
    try:
        await _get_agent_or_404(db, agent_id, tid)

        wf = Workflow(
            agent_id=agent_id,
            tenant_id=tid,
            name=body.name,
            description=body.description,
            definition=body.definition.model_dump(),
            input_schema=body.input_schema,
            output_schema=body.output_schema,
            tags=body.tags,
            trigger_type=body.trigger_type,
            trigger_config=body.trigger_config,
            is_active=False,
            version=1,
        )
        db.add(wf)
        await db.commit()
        await db.refresh(wf)
        return wf
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("create_workflow_error", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to create workflow.")
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# List workflows
# ---------------------------------------------------------------------------

@router.get("/{agent_id}/workflows", response_model=list[WorkflowResponse])
async def list_workflows(
    agent_id: uuid.UUID,
    request: Request,
    active_only: bool = False,
):
    tid_str = _tenant_id(request)
    tid = uuid.UUID(tid_str)

    db = await _get_db_session(tid_str)
    try:
        await _get_agent_or_404(db, agent_id, tid)

        q = select(Workflow).where(
            Workflow.agent_id == agent_id,
            Workflow.tenant_id == tid,
        )
        if active_only:
            q = q.where(Workflow.is_active.is_(True))
        q = q.order_by(Workflow.created_at.desc())

        result = await db.execute(q)
        return result.scalars().all()
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Get workflow
# ---------------------------------------------------------------------------

@router.get("/{agent_id}/workflows/{flow_id}", response_model=WorkflowResponse)
async def get_workflow(
    agent_id: uuid.UUID,
    flow_id: uuid.UUID,
    request: Request,
):
    tid_str = _tenant_id(request)
    tid = uuid.UUID(tid_str)

    db = await _get_db_session(tid_str)
    try:
        return await _get_workflow_or_404(db, flow_id, agent_id, tid)
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Update workflow
# ---------------------------------------------------------------------------

@router.put("/{agent_id}/workflows/{flow_id}", response_model=WorkflowResponse)
async def update_workflow(
    agent_id: uuid.UUID,
    flow_id: uuid.UUID,
    body: WorkflowUpdate,
    request: Request,
):
    tid_str = _tenant_id(request)
    tid = uuid.UUID(tid_str)

    db = await _get_db_session(tid_str)
    try:
        wf = await _get_workflow_or_404(db, flow_id, agent_id, tid)
        
        # Validate cron expression if trigger_type is cron (either updating type or config)
        if (body.trigger_type == "cron" or 
            (body.trigger_config is not None and 
             (body.trigger_type is None and wf.trigger_type == "cron"))):
            from croniter import croniter, CroniterBadCronError
            # Determine which schedule to validate
            if body.trigger_config and "schedule" in body.trigger_config:
                schedule = body.trigger_config["schedule"]
            elif body.trigger_config is None and wf.trigger_config:
                schedule = wf.trigger_config.get("schedule", "")
            else:
                schedule = ""
                
            if not schedule:
                raise HTTPException(status_code=422, detail="Cron schedule is required for cron trigger type")
            try:
                croniter(schedule)
            except CroniterBadCronError:
                raise HTTPException(status_code=422, detail=f"Invalid cron expression: {schedule}")

        if body.name is not None:
            wf.name = body.name
        if body.description is not None:
            wf.description = body.description
        if body.definition is not None:
            wf.definition = body.definition.model_dump()
        if body.input_schema is not None:
            wf.input_schema = body.input_schema
        if body.output_schema is not None:
            wf.output_schema = body.output_schema
        if body.tags is not None:
            wf.tags = body.tags
        if body.trigger_type is not None:
            wf.trigger_type = body.trigger_type
        if body.trigger_config is not None:
            wf.trigger_config = body.trigger_config

        wf.version += 1

        await db.commit()
        await db.refresh(wf)

        # If active, re-register the updated tool definition
        if wf.is_active:
            registry = WorkflowRegistry(db)
            await registry.register(wf)

        return wf
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("update_workflow_error", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to update workflow.")
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Delete (deactivate) workflow
# ---------------------------------------------------------------------------

@router.delete("/{agent_id}/workflows/{flow_id}", status_code=204)
async def delete_workflow(
    agent_id: uuid.UUID,
    flow_id: uuid.UUID,
    request: Request,
):
    tid_str = _tenant_id(request)
    tid = uuid.UUID(tid_str)

    db = await _get_db_session(tid_str)
    try:
        wf = await _get_workflow_or_404(db, flow_id, agent_id, tid)

        if wf.is_active:
            registry = WorkflowRegistry(db)
            await registry.deregister(wf)
            wf.is_active = False

        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("delete_workflow_error", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to delete workflow.")
    finally:
        await db.close()


@router.post("/{agent_id}/workflows/{flow_id}/clone", response_model=WorkflowResponse, status_code=201)
async def clone_workflow(
    agent_id: uuid.UUID,
    flow_id: uuid.UUID,
    request: Request,
):
    """Clone an existing workflow into a new workflow."""
    tid_str = _tenant_id(request)
    tid = uuid.UUID(tid_str)

    db = await _get_db_session(tid_str)
    try:
        original_wf = await _get_workflow_or_404(db, flow_id, agent_id, tid)
        
        # Create clone
        cloned_wf = Workflow(
            agent_id=agent_id,
            tenant_id=tid,
            name=f"{original_wf.name} (Copy)",
            description=original_wf.description,
            definition=original_wf.definition.copy(),
            input_schema=original_wf.input_schema.copy() if original_wf.input_schema else None,
            output_schema=original_wf.output_schema.copy() if original_wf.output_schema else None,
            tags=original_wf.tags.copy(),
            trigger_type=original_wf.trigger_type,
            trigger_config=original_wf.trigger_config.copy() if original_wf.trigger_config else None,
            is_active=False,
            version=1,
        )
        
        db.add(cloned_wf)
        await db.commit()
        await db.refresh(cloned_wf)
        
        return cloned_wf
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("clone_workflow_error", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to clone workflow.")
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Activate workflow → register as MCP tool
# ---------------------------------------------------------------------------

@router.post("/{agent_id}/workflows/{flow_id}/activate", response_model=WorkflowResponse)
async def activate_workflow(
    agent_id: uuid.UUID,
    flow_id: uuid.UUID,
    request: Request,
):
    tid_str = _tenant_id(request)
    tid = uuid.UUID(tid_str)

    db = await _get_db_session(tid_str)
    try:
        wf = await _get_workflow_or_404(db, flow_id, agent_id, tid)

        registry = WorkflowRegistry(db)
        await registry.register(wf)

        wf.is_active = True
        await db.commit()
        await db.refresh(wf)
        return wf
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("activate_workflow_error", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to activate workflow.")
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Deactivate workflow → deregister MCP tool
# ---------------------------------------------------------------------------

@router.post("/{agent_id}/workflows/{flow_id}/deactivate", response_model=WorkflowResponse)
async def deactivate_workflow(
    agent_id: uuid.UUID,
    flow_id: uuid.UUID,
    request: Request,
):
    tid_str = _tenant_id(request)
    tid = uuid.UUID(tid_str)

    db = await _get_db_session(tid_str)
    try:
        wf = await _get_workflow_or_404(db, flow_id, agent_id, tid)

        registry = WorkflowRegistry(db)
        await registry.deregister(wf)

        wf.is_active = False
        await db.commit()
        await db.refresh(wf)
        return wf
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("deactivate_workflow_error", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to deactivate workflow.")
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Get execution state
# ---------------------------------------------------------------------------

@router.get(
    "/{agent_id}/workflows/{flow_id}/executions/{session_id}",
    response_model=Optional[WorkflowExecutionResponse],
)
async def get_execution(
    agent_id: uuid.UUID,
    flow_id: uuid.UUID,
    session_id: str,
    request: Request,
):
    tid_str = _tenant_id(request)
    tid = uuid.UUID(tid_str)

    db = await _get_db_session(tid_str)
    try:
        await _get_workflow_or_404(db, flow_id, agent_id, tid)

        execution = await db.scalar(
            select(WorkflowExecution).where(
                WorkflowExecution.workflow_id == flow_id,
                WorkflowExecution.session_id == session_id,
                WorkflowExecution.tenant_id == tid,
            ).order_by(WorkflowExecution.created_at.desc())
        )
        if not execution:
            return None
        return execution
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Advance execution (manual / testing endpoint)
# ---------------------------------------------------------------------------

@router.post("/{agent_id}/workflows/{flow_id}/advance", response_model=WorkflowAdvanceResult)
async def advance_execution(
    agent_id: uuid.UUID,
    flow_id: uuid.UUID,
    body: WorkflowAdvanceRequest,
    request: Request,
):
    tid_str = _tenant_id(request)
    tid = uuid.UUID(tid_str)

    db = await _get_db_session(tid_str)
    try:
        wf = await _get_workflow_or_404(db, flow_id, agent_id, tid)

        engine = WorkflowEngine(db=db)

        # Find existing execution for this session, or create new
        execution = await db.scalar(
            select(WorkflowExecution).where(
                WorkflowExecution.workflow_id == flow_id,
                WorkflowExecution.session_id == body.session_id,
                WorkflowExecution.tenant_id == tid,
            ).order_by(WorkflowExecution.created_at.desc())
        )

        if execution is None:
            execution = await engine.create_execution(
                workflow_id=flow_id,
                session_id=body.session_id,
                tenant_id=tid,
                initial_context=body.event_payload or {},
            )
            await db.flush()

        result = await engine.advance(
            execution_id=execution.id,
            user_input=body.user_input,
            event_payload=body.event_payload,
        )
        await db.commit()
        return result
    except (WorkflowNotFoundError, ExecutionNotFoundError) as exc:
        await db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("advance_execution_error", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to advance workflow execution.")
    finally:
        await db.close()
