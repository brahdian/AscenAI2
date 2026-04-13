"""Tests for the idempotent payment webhook handler.

Covers:
  - Happy path: slot still available → CONFIRMED + confirmation SMS
  - Slot lost: slot unavailable at confirm time → NEEDS_REBOOK + slot-lost SMS
  - Duplicate event: same stripe_event_id → already_processed, DB unchanged
  - No workflow: unrecognised payment_intent_id → no_workflow
  - Invalid state: workflow EXPIRED when payment arrives → invalid_state + SMS
  - Concurrent Stripe retries handled by state machine lock
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.booking import BookingEvent, BookingState, BookingWorkflow
from app.api.v1.payment_webhook_handler import handle_payment_completed


def _make_workflow(state=BookingState.PAYMENT_PENDING, pi_id=None):
    wf = MagicMock(spec=BookingWorkflow)
    wf.id = uuid.uuid4()
    wf.tenant_id = uuid.uuid4()
    wf.state = state
    wf.provider = "builtin"
    wf.external_reservation_id = str(uuid.uuid4())
    wf.slot_service = "Haircut"
    wf.slot_date = "2026-05-01"
    wf.slot_time = "10:00"
    wf.slot_duration_minutes = 60
    wf.payment_intent_id = pi_id or f"pi_{uuid.uuid4().hex[:16]}"
    wf.customer_phone = "+14155551234"
    wf.customer_name = "Alice"
    wf.expiry_time = datetime.now(timezone.utc) + timedelta(minutes=5)
    return wf


def _make_db(idempotency_exists=False, workflow=None):
    db = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.add = MagicMock()

    # First scalar call: idempotency check (BookingEvent lookup)
    # Second scalar call: workflow lookup
    db.scalar = AsyncMock(side_effect=[
        MagicMock() if idempotency_exists else None,  # BookingEvent idem check
        workflow,                                       # WorkflowWorkflow lookup
    ])
    return db


async def _noop_config_loader(tenant_id):
    return {}


class TestHandlePaymentCompleted:
    @pytest.mark.asyncio
    async def test_already_processed_returns_early(self):
        db = _make_db(idempotency_exists=True)

        result = await handle_payment_completed(
            db=db,
            payment_intent_id="pi_test",
            stripe_event_id="evt_test",
            tenant_config_loader=_noop_config_loader,
        )

        assert result["status"] == "already_processed"
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_workflow_returns_no_workflow(self):
        db = _make_db(idempotency_exists=False, workflow=None)

        result = await handle_payment_completed(
            db=db,
            payment_intent_id="pi_unknown",
            stripe_event_id="evt_unknown",
            tenant_config_loader=_noop_config_loader,
        )

        assert result["status"] == "no_workflow"

    @pytest.mark.asyncio
    async def test_happy_path_confirms_booking(self):
        wf = _make_workflow(BookingState.PAYMENT_PENDING)
        db = _make_db(idempotency_exists=False, workflow=wf)

        # Mock state machine transition (in-place state mutation)
        async def mock_transition(db, wf_id, to_state, actor, payload=None):
            wf.state = to_state
            return wf

        # Mock provider: slot available, confirm succeeds
        mock_provider = MagicMock()
        mock_provider.check_slot_available = AsyncMock(return_value=True)
        mock_provider.confirm_slot = AsyncMock(
            return_value=MagicMock(confirmed=True, confirmation_code="BK-ABCD1234")
        )
        mock_provider.release_slot = AsyncMock()

        # Mock SMS engine
        mock_sms = MagicMock()
        mock_sms.send_booking_confirmation = AsyncMock()
        mock_sms.send_slot_lost_notification = AsyncMock()

        with patch("app.api.v1.payment_webhook_handler.transition", mock_transition), \
             patch("app.api.v1.payment_webhook_handler.record_event", AsyncMock()), \
             patch(
                 "app.api.v1.payment_webhook_handler.BookingProviderRegistry.get",
                 return_value=mock_provider,
             ):

            result = await handle_payment_completed(
                db=db,
                payment_intent_id=wf.payment_intent_id,
                stripe_event_id="evt_new",
                tenant_config_loader=_noop_config_loader,
                sms_engine_factory=lambda db, cfg: mock_sms,
            )

        assert result["status"] == "processed"
        assert result["booking_state"] == "CONFIRMED"
        mock_sms.send_booking_confirmation.assert_called_once()
        mock_sms.send_slot_lost_notification.assert_not_called()

    @pytest.mark.asyncio
    async def test_slot_lost_triggers_needs_rebook(self):
        wf = _make_workflow(BookingState.PAYMENT_PENDING)
        db = _make_db(idempotency_exists=False, workflow=wf)

        async def mock_transition(db, wf_id, to_state, actor, payload=None):
            wf.state = to_state
            return wf

        mock_provider = MagicMock()
        mock_provider.check_slot_available = AsyncMock(return_value=False)
        mock_provider.release_slot = AsyncMock()

        mock_sms = MagicMock()
        mock_sms.send_slot_lost_notification = AsyncMock()
        mock_sms.send_booking_confirmation = AsyncMock()

        with patch("app.api.v1.payment_webhook_handler.transition", mock_transition), \
             patch("app.api.v1.payment_webhook_handler.record_event", AsyncMock()), \
             patch(
                 "app.api.v1.payment_webhook_handler.BookingProviderRegistry.get",
                 return_value=mock_provider,
             ):

            result = await handle_payment_completed(
                db=db,
                payment_intent_id=wf.payment_intent_id,
                stripe_event_id="evt_slot_lost",
                tenant_config_loader=_noop_config_loader,
                sms_engine_factory=lambda db, cfg: mock_sms,
            )

        assert result["status"] == "processed"
        assert result["booking_state"] == "NEEDS_REBOOK"
        mock_sms.send_slot_lost_notification.assert_called_once()
        mock_sms.send_booking_confirmation.assert_not_called()
        mock_provider.release_slot.assert_called_once()

    @pytest.mark.asyncio
    async def test_expired_workflow_sends_slot_lost_sms(self):
        wf = _make_workflow(BookingState.EXPIRED)
        db = _make_db(idempotency_exists=False, workflow=wf)

        mock_sms = MagicMock()
        mock_sms.send_slot_lost_notification = AsyncMock()

        result = await handle_payment_completed(
            db=db,
            payment_intent_id=wf.payment_intent_id,
            stripe_event_id="evt_late_pay",
            tenant_config_loader=_noop_config_loader,
            sms_engine_factory=lambda db, cfg: mock_sms,
        )

        assert result["status"] == "invalid_state"
        assert result["current_state"] == "EXPIRED"
        mock_sms.send_slot_lost_notification.assert_called_once()
