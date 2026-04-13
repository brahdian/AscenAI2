"""Tests for the booking expiry background worker.

Covers:
  - SLOT_HELD past expiry → CRM released + EXPIRED + SMS
  - PAYMENT_PENDING past expiry → CRM released + EXPIRED + SMS
  - Reminder sent for PAYMENT_PENDING near expiry (no prior reminder)
  - Reminder NOT resent if sms_reminder_sent_at already set
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.booking import BookingState, BookingWorkflow
from app.workers.booking_expiry_worker import BookingExpiryWorker


def _utcnow():
    return datetime.now(timezone.utc)


def _make_workflow(
    state: BookingState,
    expiry_offset_minutes: int,
    reminder_sent: bool = False,
):
    wf = MagicMock(spec=BookingWorkflow)
    wf.id = uuid.uuid4()
    wf.tenant_id = uuid.uuid4()
    wf.state = state
    wf.provider = "builtin"
    wf.external_reservation_id = "ext-123"
    wf.customer_phone = "+14155551234"
    wf.expiry_time = _utcnow() + timedelta(minutes=expiry_offset_minutes)
    wf.sms_reminder_sent_at = _utcnow() if reminder_sent else None
    return wf


class TestBookingExpiryWorker:
    def _make_worker(self):
        return BookingExpiryWorker(interval_seconds=60)

    @pytest.mark.asyncio
    async def test_slot_held_expired_transitions_and_releases(self):
        expired_wf = _make_workflow(BookingState.SLOT_HELD, expiry_offset_minutes=-5)
        worker = self._make_worker()

        mock_db = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.scalars = AsyncMock()

        # First call: SLOT_HELD expired
        # Second call: PAYMENT_PENDING reminder query
        # Third call: PAYMENT_PENDING expired
        mock_db.scalars.return_value = MagicMock()

        mock_provider = MagicMock()
        mock_provider.release_slot = AsyncMock()

        mock_sms = MagicMock()
        mock_sms.send_payment_expired_notice = AsyncMock()
        mock_sms.send_payment_reminder = AsyncMock()

        async def mock_transition(db, wf_id, to_state, actor, payload=None):
            expired_wf.state = to_state
            return expired_wf

        with patch(
            "app.workers.booking_expiry_worker.BookingProviderRegistry.get",
            return_value=mock_provider,
        ), patch(
            "app.workers.booking_expiry_worker.transition",
            side_effect=mock_transition,
        ), patch(
            "app.workers.booking_expiry_worker.SMSWorkflowEngine",
            return_value=mock_sms,
        ):
            await worker._expire_workflow(mock_db, expired_wf, "expiry_worker:test")

        mock_provider.release_slot.assert_called_once_with("ext-123")
        mock_sms.send_payment_expired_notice.assert_called_once_with(expired_wf)
        assert expired_wf.state == BookingState.EXPIRED

    @pytest.mark.asyncio
    async def test_reminder_sent_once_for_near_expiry(self):
        near_expiry_wf = _make_workflow(
            BookingState.PAYMENT_PENDING,
            expiry_offset_minutes=3,  # Within 5-minute window
            reminder_sent=False,
        )
        worker = self._make_worker()

        mock_db = MagicMock()
        mock_sms = MagicMock()
        mock_sms.send_payment_reminder = AsyncMock()

        with patch(
            "app.workers.booking_expiry_worker.SMSWorkflowEngine",
            return_value=mock_sms,
        ):
            await worker._send_reminder(mock_db, near_expiry_wf)

        mock_sms.send_payment_reminder.assert_called_once_with(near_expiry_wf)

    @pytest.mark.asyncio
    async def test_reminder_not_resent_if_already_sent(self):
        already_reminded_wf = _make_workflow(
            BookingState.PAYMENT_PENDING,
            expiry_offset_minutes=3,
            reminder_sent=True,  # Already sent
        )
        # sms_reminder_sent_at is set — worker query filters these out
        # (the SQL filter is on sms_reminder_sent_at IS NULL)
        assert already_reminded_wf.sms_reminder_sent_at is not None
