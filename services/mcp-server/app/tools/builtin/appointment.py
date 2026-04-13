"""Built-in appointment booking tool handlers.

Production implementation:
  1. Detect booking provider from tenant_config["booking_provider"]
  2. Call provider.hold_slot() — creates tentative reservation in external CRM
  3. Create BookingWorkflow in our DB (state=SLOT_HELD)
  4. Create Stripe payment link (idempotent via payment_idempotency_key)
  5. Transition workflow to PAYMENT_PENDING
  6. Send payment link via SMS if customer phone is provided
  7. Return PAYMENT_PENDING status to AI — NOT "confirmed"

The appointment is only confirmed once:
  * Payment webhook fires (Stripe payment_intent.succeeded)
  * Slot is re-verified still available with the CRM
  * CRM booking is finalized
  * Confirmation SMS sent

Slot holds expire after tenant_config["slot_hold_ttl_minutes"] (default 15).
The BookingExpiryWorker releases expired holds every 60 seconds.
"""
from __future__ import annotations

import uuid

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# JSON Schemas (used by MCP tool registry)
# ---------------------------------------------------------------------------

APPOINTMENT_BOOK_SCHEMA = {
    "type": "object",
    "required": ["service", "date", "time", "customer_name"],
    "properties": {
        "service": {"type": "string"},
        "date": {"type": "string", "description": "YYYY-MM-DD"},
        "time": {"type": "string", "description": "HH:MM"},
        "customer_name": {"type": "string"},
        "phone": {"type": "string", "description": "E.164 format, e.g. +14155551234"},
        "email": {"type": "string"},
        "duration_minutes": {"type": "integer", "default": 60},
        "notes": {"type": "string"},
    },
}

APPOINTMENT_BOOK_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "workflow_id": {"type": "string"},
        "status": {"type": "string"},
        "slot_held_until": {"type": "string"},
        "payment_link": {"type": "string"},
        "message": {"type": "string"},
    },
}

APPOINTMENT_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "date": {"type": "string", "description": "YYYY-MM-DD"},
        "service": {"type": "string"},
    },
}

APPOINTMENT_LIST_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "slots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "time": {"type": "string"},
                    "available": {"type": "boolean"},
                },
            },
        }
    },
}

APPOINTMENT_CANCEL_SCHEMA = {
    "type": "object",
    "required": ["appointment_id"],
    "properties": {"appointment_id": {"type": "string"}},
}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def handle_appointment_book(parameters: dict, tenant_config: dict) -> dict:
    """Reserve a slot, create a payment link, send SMS.

    Returns status=PAYMENT_PENDING — the booking is NOT confirmed until
    payment is received and the slot is re-verified with the external CRM.
    """
    from app.core.database import SessionLocal
    from app.models.booking import BookingState, BookingWorkflow
    from app.services.booking_provider import BookingProviderRegistry, SlotUnavailableError
    from app.services.booking_state_machine import transition
    from app.services.sms_workflow_engine import SMSWorkflowEngine

    workflow_id = uuid.uuid4()
    payment_idempotency_key = str(uuid.uuid4())
    slot_hold_ttl: int = int(tenant_config.get("slot_hold_ttl_minutes", 15))
    provider_name: str = tenant_config.get("booking_provider", "builtin")
    provider = BookingProviderRegistry.get(provider_name, tenant_config)

    # ── 1. Tentative hold in external CRM ─────────────────────────────────
    try:
        hold = await provider.hold_slot(
            workflow_id=workflow_id,
            service=parameters["service"],
            slot_date=parameters["date"],
            slot_time=parameters["time"],
            duration_minutes=int(parameters.get("duration_minutes", 60)),
            customer_name=parameters["customer_name"],
            customer_email=parameters.get("email", ""),
            customer_phone=parameters.get("phone", ""),
            ttl_minutes=slot_hold_ttl,
        )
    except SlotUnavailableError as e:
        logger.info(
            "appointment_slot_unavailable",
            service=parameters["service"],
            date=parameters["date"],
            time=parameters["time"],
        )
        return {"status": "SLOT_UNAVAILABLE", "message": str(e)}
    except Exception as e:
        logger.error("appointment_hold_failed", error=str(e))
        return {"status": "ERROR", "message": f"Could not reserve slot: {e}"}

    # ── 2. Persist workflow + transitions ──────────────────────────────────
    async with SessionLocal() as db:
        wf = BookingWorkflow(
            id=workflow_id,
            tenant_id=uuid.UUID(str(tenant_config.get("tenant_id", uuid.uuid4()))),
            session_id=(
                uuid.UUID(str(tenant_config["session_id"]))
                if tenant_config.get("session_id") else None
            ),
            customer_name=parameters["customer_name"],
            customer_phone=parameters.get("phone", ""),
            customer_email=parameters.get("email", ""),
            provider=provider_name,
            external_reservation_id=hold.external_id,
            external_reservation_url=hold.external_url,
            slot_service=parameters["service"],
            slot_date=parameters["date"],
            slot_time=parameters["time"],
            slot_duration_minutes=int(parameters.get("duration_minutes", 60)),
            state=BookingState.INITIATED,
            payment_idempotency_key=payment_idempotency_key,
            expiry_time=hold.held_until,
        )
        db.add(wf)
        await db.flush()

        await transition(db, workflow_id, BookingState.SLOT_HELD, actor="appointment_tool")

        # ── 3. Stripe payment link (idempotent via key) ────────────────────
        payment_result = await _create_payment_link(
            tenant_config=tenant_config,
            parameters=parameters,
            workflow_id=workflow_id,
            idempotency_key=payment_idempotency_key,
        )

        if payment_result.get("error"):
            # Roll back CRM hold
            try:
                await provider.release_slot(hold.external_id)
            except Exception as release_err:
                logger.error("appointment_release_on_payment_fail", error=str(release_err))
            await db.rollback()
            return {
                "status": "ERROR",
                "message": f"Payment link creation failed: {payment_result['error']}",
            }

        wf.payment_link_url = payment_result["url"]
        wf.payment_intent_id = payment_result.get("payment_intent_id")

        await transition(db, workflow_id, BookingState.PAYMENT_PENDING, actor="appointment_tool")

        # ── 4. SMS if phone provided ───────────────────────────────────────
        if parameters.get("phone"):
            sms = SMSWorkflowEngine(db, tenant_config)
            await sms.send_payment_link(wf)

        await db.commit()

    logger.info(
        "appointment_workflow_created",
        workflow_id=str(workflow_id),
        provider=provider_name,
        slot=f"{parameters['date']} {parameters['time']}",
        ttl_minutes=slot_hold_ttl,
    )

    return {
        "workflow_id": str(workflow_id),
        "status": "PAYMENT_PENDING",
        "slot_held_until": hold.held_until.isoformat(),
        "payment_link": payment_result["url"],
        "message": (
            f"Slot reserved for {slot_hold_ttl} minutes. "
            f"Complete payment to confirm your {parameters['service']} appointment "
            f"on {parameters['date']} at {parameters['time']}: {payment_result['url']}"
        ),
    }


async def handle_appointment_list(parameters: dict, tenant_config: dict) -> dict:
    """List available appointment slots from the configured provider."""
    date = parameters.get("date", "today")
    service = parameters.get("service", "")
    provider_name = tenant_config.get("booking_provider", "builtin")

    if provider_name == "calendly":
        return await _list_calendly_slots(date, service, tenant_config)
    if provider_name == "google_calendar":
        return await _list_gcal_slots(date, service, tenant_config)

    # Builtin / custom: return demo hourly slots
    slots = [
        {"time": f"{h:02d}:00", "available": h % 2 == 0}
        for h in range(9, 18)
    ]
    return {"date": date, "slots": slots}


async def handle_appointment_cancel(parameters: dict, tenant_config: dict) -> dict:
    """Cancel a booking workflow and release the CRM hold."""
    from sqlalchemy import select
    from app.core.database import SessionLocal
    from app.models.booking import BookingState, BookingWorkflow
    from app.services.booking_provider import BookingProviderRegistry
    from app.services.booking_state_machine import transition

    appointment_id = parameters.get("appointment_id", "")

    async with SessionLocal() as db:
        try:
            wf_uuid = uuid.UUID(appointment_id)
        except ValueError:
            return {"status": "error", "message": f"Invalid appointment_id: {appointment_id}"}

        wf = await db.scalar(
            select(BookingWorkflow).where(BookingWorkflow.id == wf_uuid)
        )
        if not wf:
            return {"status": "error", "message": f"Appointment {appointment_id} not found"}

        if wf.external_reservation_id:
            try:
                provider = BookingProviderRegistry.get(wf.provider, tenant_config)
                await provider.release_slot(wf.external_reservation_id)
            except Exception as e:
                logger.error("appointment_cancel_crm_release_failed", error=str(e))

        try:
            await transition(db, wf.id, BookingState.FAILED, actor="user_cancel",
                             payload={"reason": "cancelled_by_user"})
        except Exception as e:
            logger.error("appointment_cancel_transition_failed", error=str(e))

        await db.commit()

    return {
        "appointment_id": appointment_id,
        "status": "cancelled",
        "message": f"Appointment {appointment_id} has been cancelled.",
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

async def _create_payment_link(
    tenant_config: dict,
    parameters: dict,
    workflow_id: uuid.UUID,
    idempotency_key: str,
) -> dict:
    """Create a Stripe payment link via the existing adapter."""
    from app.integrations.adapters.stripe import StripeAdapter

    # Amount: prefer service_price (dollars), fall back to service_price_cents
    amount_cents = tenant_config.get("service_price_cents")
    amount_dollars = tenant_config.get("service_price")
    if amount_cents:
        amount = float(amount_cents) / 100.0
    elif amount_dollars:
        amount = float(amount_dollars)
    else:
        amount = 0.0

    currency = tenant_config.get("currency", "usd")
    description = f"{parameters['service']} — {parameters['date']} {parameters['time']}"

    stripe_key = (
        tenant_config.get("stripe_secret_key")
        or tenant_config.get("secret_key")
        or ""
    )

    if not stripe_key:
        logger.warning("appointment_no_stripe_key_dev_mode", workflow_id=str(workflow_id))
        return {
            "url": f"https://pay.stripe.com/dev-mock/{str(workflow_id)[:8]}",
            "payment_link_id": f"dev-{str(workflow_id)[:8]}",
            "payment_intent_id": None,
        }

    try:
        adapter = StripeAdapter()
        return await adapter.execute(
            "CreatePaymentLink",
            {
                "amount": amount,
                "currency": currency,
                "description": description,
                "idempotency_key": idempotency_key,
                "metadata": {
                    "workflow_id": str(workflow_id),
                    "tenant_id": str(tenant_config.get("tenant_id", "")),
                },
            },
            {"secret_key": stripe_key},
        )
    except Exception as exc:
        logger.error("appointment_stripe_link_failed", error=str(exc))
        return {"error": str(exc)}


async def _list_calendly_slots(date: str, service: str, tenant_config: dict) -> dict:
    try:
        from app.integrations.adapters.calendly import CalendlyAdapter
        adapter = CalendlyAdapter()
        return await adapter.execute(
            "CheckAvailability",
            {"date": date},
            {
                "api_token": tenant_config.get("calendly_api_token", ""),
                "event_type_uuid": tenant_config.get("calendly_event_type_uuid", ""),
            },
        )
    except Exception as exc:
        logger.warning("calendly_list_slots_failed", error=str(exc))
        return {"date": date, "slots": [], "error": str(exc)}


async def _list_gcal_slots(date: str, service: str, tenant_config: dict) -> dict:
    try:
        from app.integrations.adapters.google_calendar import GoogleCalendarAdapter
        adapter = GoogleCalendarAdapter()
        return await adapter.execute(
            "CheckAvailability",
            {"date": date},
            {
                "access_token": tenant_config.get("gcal_access_token", ""),
                "calendar_id": tenant_config.get("gcal_calendar_id", "primary"),
            },
        )
    except Exception as exc:
        logger.warning("gcal_list_slots_failed", error=str(exc))
        return {"date": date, "slots": [], "error": str(exc)}
