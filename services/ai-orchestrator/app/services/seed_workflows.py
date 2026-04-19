"""Seed prebuilt workflow definitions into the system.

These are platform-level workflow templates stored as inactive workflows
under a special system tenant. Operators can clone these, assign them to
agents, and activate them.

Idempotent — safe to call on every startup. Each prebuilt has a fixed UUID
that never changes across deployments; lookup is by that UUID, not by name.

Prebuilt workflows
------------------
1. appointment_payment   — Book appointment + collect payment via Stripe
2. lead_qualification    — Score and route sales leads via LLM
3. support_ticket        — Collect issue details + create ticket
4. order_placement       — Pizza/product order collection + confirmation
"""
from __future__ import annotations

import structlog
from sqlalchemy import select

from app.core.database import AsyncSessionLocal

logger = structlog.get_logger(__name__)

# System tenant/agent UUIDs — fixed, never change across deployments.
_SYSTEM_TENANT_ID = "00000000-0000-0000-0000-000000000001"
_SYSTEM_AGENT_ID  = "00000000-0000-0000-0000-000000000001"

# Fixed UUIDs for each prebuilt workflow — used for idempotent upsert.
# These never change; altering them would create duplicate rows on next boot.
_PREBUILT_IDS = {
    "appointment_payment": "10000000-0000-0000-0000-000000000001",
    "lead_qualification":  "10000000-0000-0000-0000-000000000002",
    "support_ticket":      "10000000-0000-0000-0000-000000000003",
    "order_placement":     "10000000-0000-0000-0000-000000000004",
    # Orchestrator showcase workflow
    "orchestrator_demo":   "10000000-0000-0000-0000-000000000005",
}


_PREBUILTS = [
    # ------------------------------------------------------------------
    # 1. Appointment Booking with Payment
    # ------------------------------------------------------------------
    {
        "prebuilt_key": "appointment_payment",
        "name": "Appointment Booking with Payment",
        "description": (
            "Books an appointment for a customer, collects payment via Stripe, "
            "and sends confirmation SMS. Call this when a customer wants to schedule a service."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "service":        {"type": "string", "description": "Service to book (e.g. Haircut)"},
                "customer_name":  {"type": "string"},
                "customer_phone": {"type": "string"},
            },
            "required": ["service", "customer_name", "customer_phone"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "booking_result": {"type": "object"},
                "status":         {"type": "string"},
            },
        },
        "tags": ["booking", "payment", "appointment"],
        "definition": {
            "entry_node_id": "collect_date",
            "variables": {},
            "nodes": [
                {
                    "id": "collect_date",
                    "type": "INPUT",
                    "label": "Collect preferred date",
                    "position": {"x": 100, "y": 100},
                    "config": {
                        "prompt": "What date works best for your {{service}} appointment? (YYYY-MM-DD)",
                        "variable": "preferred_date",
                        "validation_regex": "\\d{4}-\\d{2}-\\d{2}",
                        "error_message": "Please enter a date in YYYY-MM-DD format.",
                    },
                },
                {
                    "id": "show_slots",
                    "type": "TOOL_CALL",
                    "label": "List available slots",
                    "position": {"x": 100, "y": 220},
                    "config": {
                        "tool_name": "appointment_list",
                        "argument_mapping": {"date": "{{preferred_date}}", "service": "{{service}}"},
                        "output_variable": "available_slots",
                        "on_error": "skip",
                    },
                },
                {
                    "id": "collect_time",
                    "type": "INPUT",
                    "label": "Collect preferred time",
                    "position": {"x": 100, "y": 340},
                    "config": {
                        "prompt": "Which time works for you on {{preferred_date}}?",
                        "variable": "preferred_time",
                    },
                },
                {
                    "id": "reserve_slot",
                    "type": "TOOL_CALL",
                    "label": "Reserve appointment slot",
                    "position": {"x": 100, "y": 460},
                    "config": {
                        "tool_name": "appointment_book",
                        "argument_mapping": {
                            "service":       "{{service}}",
                            "date":          "{{preferred_date}}",
                            "time":          "{{preferred_time}}",
                            "customer_name": "{{customer_name}}",
                            "phone":         "{{customer_phone}}",
                        },
                        "output_variable": "booking_result",
                        "on_error": "retry",
                        "retry_attempts": 3,
                    },
                },
                {
                    "id": "check_slot",
                    "type": "CONDITION",
                    "label": "Slot reserved?",
                    "position": {"x": 100, "y": 580},
                    "config": {
                        "expression": "isinstance(booking_result, dict) and booking_result.get('status') in ('PAYMENT_PENDING', 'confirmed', 'held')",
                    },
                },
                {
                    "id": "send_payment_sms",
                    "type": "SEND_SMS",
                    "label": "Send payment link",
                    "position": {"x": 300, "y": 700},
                    "config": {
                        "to": "{{customer_phone}}",
                        "message": "Hi {{customer_name}}, your {{service}} slot is held. Complete payment: {{booking_result.payment_link_url}}",
                        "await_reply": False,
                    },
                },
                {
                    "id": "confirm_end",
                    "type": "END",
                    "label": "Booking initiated",
                    "position": {"x": 300, "y": 820},
                    "config": {
                        "final_message": "Your {{service}} appointment is booked for {{preferred_date}} at {{preferred_time}}. A payment link has been sent to {{customer_phone}}.",
                    },
                },
                {
                    "id": "slot_unavailable",
                    "type": "SEND_SMS",
                    "label": "Slot unavailable SMS",
                    "position": {"x": -100, "y": 700},
                    "config": {
                        "to": "{{customer_phone}}",
                        "message": "Sorry {{customer_name}}, that slot is no longer available. Please call us to rebook.",
                        "await_reply": False,
                    },
                },
                {
                    "id": "retry_end",
                    "type": "END",
                    "label": "Retry prompted",
                    "position": {"x": -100, "y": 820},
                    "config": {
                        "final_message": "That slot was no longer available. I've sent you a message with next steps.",
                    },
                },
            ],
            "edges": [
                {"id": "e1", "source": "collect_date",     "target": "show_slots",        "source_handle": "default"},
                {"id": "e2", "source": "show_slots",       "target": "collect_time",       "source_handle": "default"},
                {"id": "e3", "source": "collect_time",     "target": "reserve_slot",       "source_handle": "default"},
                {"id": "e4", "source": "reserve_slot",     "target": "check_slot",         "source_handle": "default"},
                {"id": "e5", "source": "check_slot",       "target": "send_payment_sms",   "source_handle": "yes"},
                {"id": "e6", "source": "check_slot",       "target": "slot_unavailable",   "source_handle": "no"},
                {"id": "e7", "source": "send_payment_sms", "target": "confirm_end",        "source_handle": "default"},
                {"id": "e8", "source": "slot_unavailable", "target": "retry_end",          "source_handle": "default"},
            ],
        },
    },

    # ------------------------------------------------------------------
    # 2. Lead Qualification
    # ------------------------------------------------------------------
    {
        "prebuilt_key": "lead_qualification",
        "name": "Lead Qualification",
        "description": (
            "Qualifies a sales lead by collecting contact info, budget, and timeline. "
            "Scores leads with LLM and routes hot leads to the sales team via SMS."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string"},
            },
            "required": [],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "lead_score": {"type": "string"},
                "crm_result":  {"type": "object"},
            },
        },
        "tags": ["sales", "lead", "crm"],
        "definition": {
            "entry_node_id": "collect_name",
            "variables": {},
            "nodes": [
                {"id": "collect_name",    "type": "INPUT",     "label": "Name",     "position": {"x": 100, "y": 100}, "config": {"prompt": "What's your name?",                                                              "variable": "lead_name"}},
                {"id": "collect_company", "type": "INPUT",     "label": "Company",  "position": {"x": 100, "y": 220}, "config": {"prompt": "What company are you with?",                                                      "variable": "company"}},
                {"id": "collect_budget",  "type": "INPUT",     "label": "Budget",   "position": {"x": 100, "y": 340}, "config": {"prompt": "What's your estimated budget?",                                                   "variable": "budget"}},
                {"id": "collect_timeline","type": "INPUT",     "label": "Timeline", "position": {"x": 100, "y": 460}, "config": {"prompt": "When are you looking to get started?",                                            "variable": "timeline"}},
                {
                    "id": "score_lead",
                    "type": "LLM_CALL",
                    "label": "Score lead",
                    "position": {"x": 100, "y": 580},
                    "config": {
                        "prompt_template": "Rate this lead 1-10 (10=hottest). Name:{{lead_name}}, Company:{{company}}, Budget:{{budget}}, Timeline:{{timeline}}. Respond with just the number.",
                        "output_variable": "lead_score",
                        "extract_json": False,
                    },
                },
                {
                    "id": "check_score",
                    "type": "CONDITION",
                    "label": "Hot lead?",
                    "position": {"x": 100, "y": 700},
                    "config": {"expression": "int(lead_score) >= 7 if str(lead_score).isdigit() else False"},
                },
                {
                    "id": "create_crm",
                    "type": "TOOL_CALL",
                    "label": "Create CRM lead",
                    "position": {"x": 300, "y": 820},
                    "config": {
                        "tool_name": "crm_update",
                        "argument_mapping": {"name": "{{lead_name}}", "company": "{{company}}", "score": "{{lead_score}}"},
                        "output_variable": "crm_result",
                        "on_error": "skip",
                    },
                },
                {
                    "id": "notify_sales",
                    "type": "SEND_SMS",
                    "label": "Notify sales",
                    "position": {"x": 300, "y": 940},
                    "config": {
                        "to": "{{sales_phone}}",
                        "message": "Hot lead: {{lead_name}} from {{company}} (score: {{lead_score}})",
                        "await_reply": False,
                    },
                },
                {"id": "hot_end",     "type": "END", "label": "Hot lead",    "position": {"x": 300, "y": 1060}, "config": {"final_message": "Thanks {{lead_name}}! Our sales team will contact you within 2 hours."}},
                {"id": "nurture_end", "type": "END", "label": "Nurture lead", "position": {"x": -100, "y": 820}, "config": {"final_message": "Thanks {{lead_name}}! We'll send you some resources and follow up next week."}},
            ],
            "edges": [
                {"id": "e1", "source": "collect_name",    "target": "collect_company", "source_handle": "default"},
                {"id": "e2", "source": "collect_company", "target": "collect_budget",  "source_handle": "default"},
                {"id": "e3", "source": "collect_budget",  "target": "collect_timeline","source_handle": "default"},
                {"id": "e4", "source": "collect_timeline","target": "score_lead",       "source_handle": "default"},
                {"id": "e5", "source": "score_lead",      "target": "check_score",      "source_handle": "default"},
                {"id": "e6", "source": "check_score",     "target": "create_crm",       "source_handle": "yes"},
                {"id": "e7", "source": "create_crm",      "target": "notify_sales",     "source_handle": "default"},
                {"id": "e8", "source": "notify_sales",    "target": "hot_end",          "source_handle": "default"},
                {"id": "e9", "source": "check_score",     "target": "nurture_end",      "source_handle": "no"},
            ],
        },
    },

    # ------------------------------------------------------------------
    # 3. Support Ticket Creation
    # ------------------------------------------------------------------
    {
        "prebuilt_key": "support_ticket",
        "name": "Support Ticket Creation",
        "description": (
            "Creates a support ticket when a customer reports an issue. "
            "Collects issue details and priority, then confirms the ticket number."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string"},
            },
            "required": [],
        },
        "output_schema": {
            "type": "object",
            "properties": {"ticket": {"type": "object"}},
        },
        "tags": ["support", "tickets", "helpdesk"],
        "definition": {
            "entry_node_id": "collect_issue",
            "variables": {},
            "nodes": [
                {
                    "id": "collect_issue",
                    "type": "INPUT",
                    "label": "Describe issue",
                    "position": {"x": 100, "y": 100},
                    "config": {"prompt": "Please describe your issue in detail.", "variable": "issue_description"},
                },
                {
                    "id": "collect_priority",
                    "type": "INPUT",
                    "label": "Priority",
                    "position": {"x": 100, "y": 220},
                    "config": {
                        "prompt": "How urgent is this? (low / medium / high / critical)",
                        "variable": "priority",
                        "validation_regex": "low|medium|high|critical",
                        "error_message": "Please enter one of: low, medium, high, critical.",
                    },
                },
                {
                    "id": "create_ticket",
                    "type": "TOOL_CALL",
                    "label": "Create ticket",
                    "position": {"x": 100, "y": 340},
                    "config": {
                        "tool_name": "crm_update",
                        "argument_mapping": {
                            "description": "{{issue_description}}",
                            "priority":    "{{priority}}",
                            "name":        "{{customer_name}}",
                        },
                        "output_variable": "ticket",
                        "on_error": "skip",
                    },
                },
                {
                    "id": "confirm_end",
                    "type": "END",
                    "label": "Ticket created",
                    "position": {"x": 100, "y": 460},
                    "config": {
                        "final_message": "Your support ticket has been created ({{priority}} priority). Our team will respond shortly.",
                    },
                },
            ],
            "edges": [
                {"id": "e1", "source": "collect_issue",    "target": "collect_priority", "source_handle": "default"},
                {"id": "e2", "source": "collect_priority", "target": "create_ticket",    "source_handle": "default"},
                {"id": "e3", "source": "create_ticket",    "target": "confirm_end",      "source_handle": "default"},
            ],
        },
    },

    # ------------------------------------------------------------------
    # 4. Order Placement
    # ------------------------------------------------------------------
    {
        "prebuilt_key": "order_placement",
        "name": "Order Placement",
        "description": (
            "Collects customer order details (items, quantities, delivery address) "
            "and places the order. Confirms order number and estimated delivery."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_name":  {"type": "string"},
                "customer_phone": {"type": "string"},
            },
            "required": [],
        },
        "output_schema": {
            "type": "object",
            "properties": {"order_result": {"type": "object"}},
        },
        "tags": ["order", "ecommerce", "food"],
        "definition": {
            "entry_node_id": "collect_items",
            "variables": {},
            "nodes": [
                {
                    "id": "collect_items",
                    "type": "INPUT",
                    "label": "Collect order items",
                    "position": {"x": 100, "y": 100},
                    "config": {"prompt": "What would you like to order? Please list your items.", "variable": "order_items"},
                },
                {
                    "id": "collect_address",
                    "type": "INPUT",
                    "label": "Delivery address",
                    "position": {"x": 100, "y": 220},
                    "config": {"prompt": "What is the delivery address?", "variable": "delivery_address"},
                },
                {
                    "id": "collect_notes",
                    "type": "INPUT",
                    "label": "Special instructions",
                    "position": {"x": 100, "y": 340},
                    "config": {"prompt": "Any special instructions or dietary requirements? (or say 'none')", "variable": "special_notes"},
                },
                {
                    "id": "place_order",
                    "type": "TOOL_CALL",
                    "label": "Place order",
                    "position": {"x": 100, "y": 460},
                    "config": {
                        "tool_name": "pizza_order",
                        "argument_mapping": {
                            "items":    "{{order_items}}",
                            "address":  "{{delivery_address}}",
                            "notes":    "{{special_notes}}",
                            "customer": "{{customer_name}}",
                            "phone":    "{{customer_phone}}",
                        },
                        "output_variable": "order_result",
                        "on_error": "retry",
                        "retry_attempts": 2,
                    },
                },
                {
                    "id": "confirm_end",
                    "type": "END",
                    "label": "Order confirmed",
                    "position": {"x": 100, "y": 580},
                    "config": {
                        "final_message": "Your order has been placed! Estimated delivery: 30-45 minutes to {{delivery_address}}.",
                    },
                },
            ],
            "edges": [
                {"id": "e1", "source": "collect_items",   "target": "collect_address", "source_handle": "default"},
                {"id": "e2", "source": "collect_address", "target": "collect_notes",   "source_handle": "default"},
                {"id": "e3", "source": "collect_notes",   "target": "place_order",     "source_handle": "default"},
                {"id": "e4", "source": "place_order",     "target": "confirm_end",     "source_handle": "default"},
            ],
        },
    },

    # ------------------------------------------------------------------
    # 5. Orchestrator Demo — showcases CALL_WORKFLOW, PARALLEL,
    #    WAIT_FOR_SIGNAL, and CODE_EXEC in a single VIP onboarding flow
    # ------------------------------------------------------------------
    {
        "prebuilt_key": "orchestrator_demo",
        "name": "Orchestrator Demo — VIP Customer Onboarding",
        "description": (
            "Demonstrates multi-workflow orchestration. "
            "Collects VIP customer info, runs two parallel background checks "
            "(credit scoring + CRM lookup) using PARALLEL, waits for a manual "
            "approval signal via WAIT_FOR_SIGNAL, then calls a sub-workflow to "
            "create a support ticket using CALL_WORKFLOW. "
            "Uses CODE_EXEC to compute a composite risk score."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_name":  {"type": "string"},
                "customer_phone": {"type": "string"},
                "customer_email": {"type": "string"},
            },
            "required": ["customer_name"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "risk_score":          {"type": "number"},
                "parallel_results":    {"type": "array"},
                "ticket_result":       {"type": "object"},
            },
        },
        "tags": ["orchestrator", "demo", "parallel", "signals"],
        "trigger_type": "none",
        "trigger_config": {},
        "definition": {
            "entry_node_id": "collect_email",
            "variables": {
                "risk_threshold": 7,
            },
            "nodes": [
                # Step 1 — collect email
                {
                    "id": "collect_email",
                    "type": "INPUT",
                    "label": "Collect email",
                    "position": {"x": 100, "y": 100},
                    "config": {
                        "prompt": "What is {{customer_name}}'s email address?",
                        "variable": "customer_email",
                        "validation_regex": r"[^@]+@[^@]+\.[^@]+",
                        "error_message": "Please enter a valid email address.",
                    },
                },
                # Step 2 — PARALLEL: run CRM lookup + lead scoring concurrently
                # Replace workflow_id values with real workflow UUIDs assigned to this agent
                {
                    "id": "parallel_checks",
                    "type": "PARALLEL",
                    "label": "Background checks (parallel)",
                    "position": {"x": 100, "y": 240},
                    "config": {
                        "branches": [
                            {
                                "workflow_id": "10000000-0000-0000-0000-000000000003",  # support_ticket as stand-in
                                "input_mapping": {
                                    "customer_name": "{{customer_name}}",
                                    "issue_description": "CRM lookup for {{customer_email}}",
                                    "priority": "low",
                                },
                                "output_variable": "crm_branch",
                            },
                            {
                                "workflow_id": "10000000-0000-0000-0000-000000000002",  # lead_qualification
                                "input_mapping": {
                                    "customer_name": "{{customer_name}}",
                                },
                                "output_variable": "lead_branch",
                            },
                        ],
                        "join_output_key": "parallel_results",
                        "fail_fast": False,  # continue even if one branch fails
                    },
                },
                # Step 3 — CODE_EXEC: compute composite risk score from parallel results
                {
                    "id": "compute_risk",
                    "type": "CODE_EXEC",
                    "label": "Compute risk score",
                    "position": {"x": 100, "y": 380},
                    "config": {
                        "code": (
                            "len([r for r in parallel_results if r.get('status') == 'COMPLETED']) * 3 "
                            "+ (5 if customer_email else 0)"
                        ),
                        "output_variable": "risk_score",
                        "on_error": "skip",
                    },
                },
                # Step 4 — CONDITION: branch on risk score
                {
                    "id": "check_risk",
                    "type": "CONDITION",
                    "label": "High risk?",
                    "position": {"x": 100, "y": 500},
                    "config": {
                        "expression": "float(risk_score) >= float(risk_threshold)",
                    },
                },
                # Step 5a — WAIT_FOR_SIGNAL: pause for manual approval (high risk path)
                {
                    "id": "await_approval",
                    "type": "WAIT_FOR_SIGNAL",
                    "label": "Await manager approval",
                    "position": {"x": 300, "y": 620},
                    "config": {
                        "signal_name": "vip_approval",
                        "correlation_id_key": "customer_email",
                        "ttl_seconds": 86400,       # 24h
                        "output_variable": "approval_payload",
                    },
                },
                # Step 5b — auto-approve low risk path (SET_VARIABLE)
                {
                    "id": "auto_approve",
                    "type": "SET_VARIABLE",
                    "label": "Auto-approve",
                    "position": {"x": -100, "y": 620},
                    "config": {
                        "variable": "approval_payload",
                        "value": '{"approved": true, "approver": "auto"}',
                    },
                },
                # Step 6 — CALL_WORKFLOW: create an onboarding support ticket
                {
                    "id": "create_ticket",
                    "type": "CALL_WORKFLOW",
                    "label": "Create onboarding ticket",
                    "position": {"x": 100, "y": 760},
                    "config": {
                        "workflow_id": "10000000-0000-0000-0000-000000000003",  # support_ticket
                        "input_mapping": {
                            "customer_name":     "{{customer_name}}",
                            "issue_description": "VIP onboarding for {{customer_email}} — risk_score={{risk_score}}",
                            "priority":          "high",
                        },
                        "output_variable": "ticket_result",
                    },
                },
                # Step 7 — END
                {
                    "id": "summary_end",
                    "type": "END",
                    "label": "Onboarding initiated",
                    "position": {"x": 100, "y": 900},
                    "config": {
                        "final_message": (
                            "VIP onboarding complete for {{customer_name}}. "
                            "Risk score: {{risk_score}}. "
                            "Ticket created. Welcome!"
                        ),
                    },
                },
            ],
            "edges": [
                {"id": "e1", "source": "collect_email",   "target": "parallel_checks", "source_handle": "default"},
                {"id": "e2", "source": "parallel_checks", "target": "compute_risk",    "source_handle": "default"},
                {"id": "e3", "source": "compute_risk",    "target": "check_risk",      "source_handle": "default"},
                {"id": "e4", "source": "check_risk",      "target": "await_approval",  "source_handle": "yes"},
                {"id": "e5", "source": "check_risk",      "target": "auto_approve",    "source_handle": "no"},
                {"id": "e6", "source": "await_approval",  "target": "create_ticket",   "source_handle": "default"},
                {"id": "e7", "source": "auto_approve",    "target": "create_ticket",   "source_handle": "default"},
                {"id": "e8", "source": "create_ticket",   "target": "summary_end",     "source_handle": "default"},
            ],
        },
    },
]


async def seed_prebuilt_workflows() -> None:
    """Upsert prebuilt workflow definitions (system tenant, no agent_id required).

    These are reference workflows only — they have no real agent_id or tenant.
    Operators clone or activate them per-agent via the UI.
    """
    import uuid as _uuid
    from app.models.workflow import Workflow

    system_tenant = _uuid.UUID(_SYSTEM_TENANT_ID)
    system_agent  = _uuid.UUID(_SYSTEM_AGENT_ID)

    async with AsyncSessionLocal() as db:
        try:
            for defn in _PREBUILTS:
                key = defn["prebuilt_key"]
                fixed_id = _uuid.UUID(_PREBUILT_IDS[key])

                existing = await db.scalar(
                    select(Workflow).where(Workflow.id == fixed_id)
                )
                if existing:
                    # Update definition if it changed (version bump)
                    existing.name         = defn["name"]
                    existing.description  = defn["description"]
                    existing.definition   = defn["definition"]
                    existing.input_schema = defn["input_schema"]
                    existing.output_schema= defn["output_schema"]
                    existing.tags         = defn["tags"]
                    existing.version     += 1
                    logger.info("prebuilt_workflow_updated", workflow_id=str(fixed_id), key=key)
                else:
                    wf = Workflow(
                        id            = fixed_id,
                        agent_id      = system_agent,
                        tenant_id     = system_tenant,
                        name          = defn["name"],
                        description   = defn["description"],
                        definition    = defn["definition"],
                        input_schema  = defn["input_schema"],
                        output_schema = defn["output_schema"],
                        tags          = defn["tags"],
                        is_active     = False,
                        version       = 1,
                    )
                    db.add(wf)
                    logger.info("prebuilt_workflow_created", workflow_id=str(fixed_id), key=key)

            await db.commit()
            logger.info("prebuilt_workflows_seeded", count=len(_PREBUILTS))
        except Exception as exc:
            await db.rollback()
            logger.error("seed_prebuilt_workflows_error", error=str(exc))
            raise
