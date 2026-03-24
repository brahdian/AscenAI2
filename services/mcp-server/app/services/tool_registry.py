import uuid
from typing import Optional

import structlog
from sqlalchemy import select, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tool import Tool
from app.schemas.mcp import ToolRegistration, ToolUpdate

logger = structlog.get_logger(__name__)


class ToolRegistry:
    """
    Manages tool registration, retrieval, and lifecycle per tenant.
    All operations are scoped to a specific tenant_id.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def register_tool(
        self, tenant_id: str, tool_data: ToolRegistration
    ) -> Tool:
        """Register a new tool for a tenant. Raises ValueError if name already exists."""
        # Check for existing tool with same name under this tenant
        existing = await self.get_tool(tenant_id, tool_data.name)
        if existing:
            raise ValueError(
                f"Tool '{tool_data.name}' already exists for tenant '{tenant_id}'. "
                "Use update_tool to modify it."
            )

        tool = Tool(
            id=uuid.uuid4(),
            tenant_id=uuid.UUID(tenant_id),
            name=tool_data.name,
            description=tool_data.description,
            category=tool_data.category,
            input_schema=tool_data.input_schema,
            output_schema=tool_data.output_schema,
            endpoint_url=tool_data.endpoint_url,
            auth_config=tool_data.auth_config,
            rate_limit_per_minute=tool_data.rate_limit_per_minute,
            timeout_seconds=tool_data.timeout_seconds,
            is_active=True,
            is_builtin=tool_data.is_builtin,
            tool_metadata=tool_data.tool_metadata,
        )
        self.db.add(tool)
        await self.db.flush()  # Get the ID without committing
        await self.db.refresh(tool)
        logger.info(
            "tool_registered",
            tenant_id=tenant_id,
            tool_name=tool_data.name,
            tool_id=str(tool.id),
        )
        return tool

    async def get_tool(self, tenant_id: str, tool_name: str) -> Optional[Tool]:
        """Retrieve a tool by name for the given tenant."""
        result = await self.db.execute(
            select(Tool).where(
                and_(
                    Tool.tenant_id == uuid.UUID(tenant_id),
                    Tool.name == tool_name,
                    Tool.is_active == True,  # noqa: E712
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_tool_by_id(self, tenant_id: str, tool_id: str) -> Optional[Tool]:
        """Retrieve a tool by UUID for the given tenant."""
        result = await self.db.execute(
            select(Tool).where(
                and_(
                    Tool.tenant_id == uuid.UUID(tenant_id),
                    Tool.id == uuid.UUID(tool_id),
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_tools(
        self,
        tenant_id: str,
        category: Optional[str] = None,
        include_inactive: bool = False,
    ) -> list[Tool]:
        """List all tools for a tenant, optionally filtered by category."""
        conditions = [Tool.tenant_id == uuid.UUID(tenant_id)]
        if category:
            conditions.append(Tool.category == category)
        if not include_inactive:
            conditions.append(Tool.is_active == True)  # noqa: E712

        result = await self.db.execute(
            select(Tool).where(and_(*conditions)).order_by(Tool.category, Tool.name)
        )
        return list(result.scalars().all())

    async def update_tool(
        self, tenant_id: str, tool_name: str, updates: ToolUpdate
    ) -> Tool:
        """Update an existing tool. Raises ValueError if not found."""
        tool = await self.get_tool(tenant_id, tool_name)
        if not tool:
            raise ValueError(f"Tool '{tool_name}' not found for tenant '{tenant_id}'")

        update_data = updates.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(tool, field, value)

        await self.db.flush()
        await self.db.refresh(tool)
        logger.info(
            "tool_updated",
            tenant_id=tenant_id,
            tool_name=tool_name,
            updated_fields=list(update_data.keys()),
        )
        return tool

    async def delete_tool(self, tenant_id: str, tool_name: str) -> None:
        """Soft-delete a tool by setting is_active=False."""
        tool = await self.get_tool(tenant_id, tool_name)
        if not tool:
            raise ValueError(f"Tool '{tool_name}' not found for tenant '{tenant_id}'")

        tool.is_active = False
        await self.db.flush()
        logger.info("tool_deleted", tenant_id=tenant_id, tool_name=tool_name)

    async def hard_delete_tool(self, tenant_id: str, tool_name: str) -> None:
        """Permanently delete a tool and its execution history."""
        await self.db.execute(
            delete(Tool).where(
                and_(
                    Tool.tenant_id == uuid.UUID(tenant_id),
                    Tool.name == tool_name,
                )
            )
        )
        await self.db.flush()
        logger.info("tool_hard_deleted", tenant_id=tenant_id, tool_name=tool_name)

    async def get_tool_schema(self, tenant_id: str, tool_name: str) -> dict:
        """
        Return the composite JSON Schema for a tool:
        {
            "input": <input_schema>,
            "output": <output_schema>,
            "name": <name>,
            "description": <description>,
        }
        """
        tool = await self.get_tool(tenant_id, tool_name)
        if not tool:
            raise ValueError(f"Tool '{tool_name}' not found for tenant '{tenant_id}'")

        return {
            "name": tool.name,
            "description": tool.description,
            "category": tool.category,
            "input": tool.input_schema,
            "output": tool.output_schema,
        }

    async def seed_builtin_tools(self, tenant_id: str) -> list[Tool]:
        """
        Register platform-provided built-in tools for a tenant if not already present.
        Returns the list of newly created tools.
        """
        from app.tools.builtin.pizza import PIZZA_ORDER_SCHEMA, PIZZA_ORDER_OUTPUT_SCHEMA
        from app.tools.builtin.appointment import (
            APPOINTMENT_BOOK_SCHEMA,
            APPOINTMENT_BOOK_OUTPUT_SCHEMA,
            APPOINTMENT_LIST_SCHEMA,
            APPOINTMENT_LIST_OUTPUT_SCHEMA,
            APPOINTMENT_CANCEL_SCHEMA,
        )
        from app.tools.builtin.crm import (
            CRM_LOOKUP_SCHEMA,
            CRM_LOOKUP_OUTPUT_SCHEMA,
            CRM_UPDATE_SCHEMA,
        )

        builtin_definitions = [
            ToolRegistration(
                name="pizza_order",
                description="Place a pizza order via POS integration",
                category="ordering",
                input_schema=PIZZA_ORDER_SCHEMA,
                output_schema=PIZZA_ORDER_OUTPUT_SCHEMA,
                is_builtin=True,
                rate_limit_per_minute=30,
                timeout_seconds=15,
            ),
            ToolRegistration(
                name="appointment_book",
                description="Book an appointment for a customer",
                category="booking",
                input_schema=APPOINTMENT_BOOK_SCHEMA,
                output_schema=APPOINTMENT_BOOK_OUTPUT_SCHEMA,
                is_builtin=True,
            ),
            ToolRegistration(
                name="appointment_list",
                description="List available appointment slots",
                category="booking",
                input_schema=APPOINTMENT_LIST_SCHEMA,
                output_schema=APPOINTMENT_LIST_OUTPUT_SCHEMA,
                is_builtin=True,
            ),
            ToolRegistration(
                name="appointment_cancel",
                description="Cancel an existing appointment",
                category="booking",
                input_schema=APPOINTMENT_CANCEL_SCHEMA,
                output_schema={"type": "object"},
                is_builtin=True,
            ),
            ToolRegistration(
                name="crm_lookup",
                description="Look up a customer profile in the CRM",
                category="crm",
                input_schema=CRM_LOOKUP_SCHEMA,
                output_schema=CRM_LOOKUP_OUTPUT_SCHEMA,
                is_builtin=True,
            ),
            ToolRegistration(
                name="crm_update",
                description="Update a customer record in the CRM",
                category="crm",
                input_schema=CRM_UPDATE_SCHEMA,
                output_schema={"type": "object"},
                is_builtin=True,
            ),
        ]

        created = []
        for tool_def in builtin_definitions:
            try:
                tool = await self.register_tool(tenant_id, tool_def)
                created.append(tool)
            except ValueError:
                # Already exists — skip
                pass

        return created
