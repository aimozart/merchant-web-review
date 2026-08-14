from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from ops import faults, infra_faults, network_faults, tasks
from ops.faults import FAILURE_SPIKE_MARKER
from ops.models import OpsFlag, Ticket
from reviews.models import Merchant, RiskSignal, WebPresenceReview


class OpsFlagTests(TestCase):
    def test_is_set_false_when_absent(self):
        self.assertFalse(OpsFlag.is_set("nonexistent"))

    def test_set_flag_then_is_set(self):
        OpsFlag.set_flag("some_flag", True, note="test")
        self.assertTrue(OpsFlag.is_set("some_flag"))
        OpsFlag.set_flag("some_flag", False)
        self.assertFalse(OpsFlag.is_set("some_flag"))


class TicketModelTests(TestCase):
    def test_str(self):
        ticket = Ticket.objects.create(title="Something broke", priority="high")
        self.assertIn("Something broke", str(ticket))


class Tier1FaultRegistryTests(TestCase):
    """
    Full inject -> stays-broken -> real-fix -> resolves loop for every Tier 1
    fault. These are pure Django/model faults, so — unlike Tiers 2-3 — they can
    run in any environment without Docker or LocalStack, which is exactly why
    Tier 1 is the one with full automated coverage here.
    """

    def test_every_fault_is_well_formed(self):
        for key, fault in faults.FAULTS.items():
            self.assertEqual(fault.key, key)
            self.assertTrue(fault.title)
            self.assertTrue(fault.description)
            self.assertTrue(fault.real_cause)
            self.assertTrue(fault.fix_hint)
            self.assertIn(fault.priority, dict(Ticket.PRIORITY_CHOICES))
            self.assertIn(fault.category, dict(Ticket.CATEGORY_CHOICES))

    def test_stuck_review_lifecycle(self):
        ticket = faults.inject_fault("stuck_review")
        self.assertEqual(ticket.status, "open")
        self.assertFalse(faults.verify_fix(ticket))

        review = WebPresenceReview.objects.get(id=ticket.related_review_id)
        review.status = "complete"
        review.save(update_fields=["status"])

        self.assertTrue(faults.verify_fix(ticket))
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "resolved")
        self.assertIsNotNone(ticket.resolved_at)

    def test_overdue_monitoring_lifecycle(self):
        ticket = faults.inject_fault("overdue_monitoring")
        self.assertFalse(faults.verify_fix(ticket))

        WebPresenceReview.objects.create(
            merchant_id=ticket.related_merchant_id, status="complete"
        )

        self.assertTrue(faults.verify_fix(ticket))

    def test_llm_degraded_lifecycle(self):
        ticket = faults.inject_fault("llm_degraded")
        self.assertTrue(OpsFlag.is_set("llm_analysis_disabled"))
        self.assertFalse(faults.verify_fix(ticket))

        OpsFlag.set_flag("llm_analysis_disabled", False)

        self.assertTrue(faults.verify_fix(ticket))

    def test_bad_signal_category_lifecycle(self):
        ticket = faults.inject_fault("bad_signal_category")
        self.assertFalse(faults.verify_fix(ticket))

        RiskSignal.objects.filter(review_id=ticket.related_review_id).update(category="content")

        self.assertTrue(faults.verify_fix(ticket))

    def test_failure_spike_lifecycle(self):
        ticket = faults.inject_fault("failure_spike")
        self.assertEqual(
            WebPresenceReview.objects.filter(
                status="failed", error_message=FAILURE_SPIKE_MARKER
            ).count(),
            5,
        )
        self.assertFalse(faults.verify_fix(ticket))

        WebPresenceReview.objects.filter(
            status="failed", error_message=FAILURE_SPIKE_MARKER
        ).update(status="complete", error_message="")

        self.assertTrue(faults.verify_fix(ticket))

    def test_verify_fix_returns_false_for_unknown_fault_key(self):
        ticket = Ticket.objects.create(title="mystery", fault_key="does_not_exist")
        self.assertFalse(faults.verify_fix(ticket))

    def test_get_or_create_demo_merchant_is_idempotent(self):
        m1 = faults._get_or_create_demo_merchant()
        m2 = faults._get_or_create_demo_merchant()
        self.assertEqual(m1.id, m2.id)
        self.assertEqual(Merchant.objects.filter(website_url=m1.website_url).count(), 1)


class Tier2And3RegistrySanityTests(TestCase):
    """
    Tiers 2 (Docker) and 3 (real AWS/LocalStack) can't be exercised end-to-end in
    a plain test run — they require a live Docker Compose stack and a running
    LocalStack + `pulumi up`'d infra stack respectively. What *can* and should be
    verified in any environment is that every fault definition is complete and
    internally consistent, so a missing field or typo'd category fails fast in
    CI rather than only being discovered the next time someone runs the drill
    by hand against real infrastructure.
    """

    def test_every_infra_fault_is_well_formed(self):
        for key, fault in infra_faults.INFRA_FAULTS.items():
            self.assertEqual(fault.key, key)
            self.assertTrue(fault.title)
            self.assertTrue(fault.description)
            self.assertTrue(fault.real_cause)
            self.assertTrue(fault.fix_hint)
            self.assertIn(fault.priority, dict(Ticket.PRIORITY_CHOICES))
            self.assertIn(fault.category, dict(Ticket.CATEGORY_CHOICES))
            self.assertTrue(callable(fault.inject))
            self.assertTrue(callable(fault.check_resolved))

    def test_every_network_fault_is_well_formed(self):
        for key, fault in network_faults.NETWORK_FAULTS.items():
            self.assertEqual(fault.key, key)
            self.assertTrue(fault.title)
            self.assertTrue(fault.description)
            self.assertTrue(fault.real_cause)
            self.assertTrue(fault.fix_hint)
            self.assertIn(fault.priority, dict(Ticket.PRIORITY_CHOICES))
            self.assertIn(fault.category, dict(Ticket.CATEGORY_CHOICES))
            self.assertTrue(callable(fault.inject))
            self.assertTrue(callable(fault.check_resolved))


class TicketApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_inject_tier1_random_fault_via_api(self):
        response = self.client.post("/api/tickets/inject/", {"tier": 1}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertIn(response.data["title"], [f.title for f in faults.FAULTS.values()])

    def test_inject_unknown_fault_key_returns_400(self):
        response = self.client.post(
            "/api/tickets/inject/", {"tier": 1, "fault_key": "nonexistent"}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_verify_and_close_full_loop(self):
        inject_response = self.client.post(
            "/api/tickets/inject/", {"tier": 1, "fault_key": "llm_degraded"}, format="json"
        )
        ticket_id = inject_response.data["id"]

        verify_response = self.client.post(f"/api/tickets/{ticket_id}/verify/")
        self.assertFalse(verify_response.data["resolved"])

        close_attempt = self.client.post(f"/api/tickets/{ticket_id}/close/")
        self.assertEqual(close_attempt.status_code, 400)

        OpsFlag.set_flag("llm_analysis_disabled", False)
        verify_response = self.client.post(f"/api/tickets/{ticket_id}/verify/")
        self.assertTrue(verify_response.data["resolved"])

        close_response = self.client.post(f"/api/tickets/{ticket_id}/close/")
        self.assertEqual(close_response.status_code, 200)
        self.assertEqual(close_response.data["status"], "closed")

    def test_verify_non_fault_ticket_returns_400(self):
        ticket = Ticket.objects.create(title="manual ticket")
        response = self.client.post(f"/api/tickets/{ticket.id}/verify/")
        self.assertEqual(response.status_code, 400)


class ReplenishAndPagingTaskTests(TestCase):
    """
    Docker/LocalStack are deliberately mocked as unreachable in every test here
    so these run identically in CI (no Docker socket, no LocalStack) and on a
    laptop with the full stack up — they test the *decision logic*, not Tiers
    2-3's actual infrastructure calls (covered separately by the registry
    sanity tests and by hand against the real stack).
    """

    @patch("ops.tasks._localstack_reachable", return_value=False)
    @patch("ops.tasks._docker_reachable", return_value=False)
    def test_replenish_ticket_creates_a_new_open_ticket(self, mock_docker, mock_localstack):
        before = Ticket.objects.count()

        ticket_id = tasks.replenish_ticket()

        self.assertEqual(Ticket.objects.count(), before + 1)
        ticket = Ticket.objects.get(id=ticket_id)
        self.assertEqual(ticket.status, "open")
        self.assertEqual(ticket.source, "fault_injection")

    @patch("ops.tasks._within_shift_hours", return_value=True)
    @patch("ops.tasks.random.random", return_value=0.99)
    def test_maybe_page_oncall_usually_does_nothing(self, mock_random, mock_shift):
        before = Ticket.objects.count()

        result = tasks.maybe_page_oncall()

        self.assertIsNone(result)
        self.assertEqual(Ticket.objects.count(), before)

    @patch("ops.tasks.random.random", return_value=0.0)
    def test_maybe_page_oncall_never_fires_outside_shift_hours(self, mock_random):
        with patch("ops.tasks._within_shift_hours", return_value=False):
            result = tasks.maybe_page_oncall()

        self.assertIsNone(result)

    @patch("ops.tasks.time.sleep")
    @patch("ops.tasks.requests.post")
    @patch("ops.tasks.NTFY_TOPIC", "test-topic")
    @patch("ops.tasks._localstack_reachable", return_value=False)
    @patch("ops.tasks._docker_reachable", return_value=False)
    @patch("ops.tasks._within_shift_hours", return_value=True)
    @patch("ops.tasks.random.random", return_value=0.0)
    def test_maybe_page_oncall_fires_and_stops_once_acknowledged(
        self, mock_random, mock_shift, mock_docker, mock_localstack, mock_post, mock_sleep
    ):
        # Simulate the tap-to-acknowledge action landing during the first wait —
        # the escalation loop should notice on its next check and stop.
        def ack_during_wait(*args, **kwargs):
            Ticket.objects.filter(status="open").update(status="in_progress")

        mock_sleep.side_effect = ack_during_wait

        result = tasks.maybe_page_oncall()

        self.assertIsNotNone(result)
        ticket = Ticket.objects.get(id=result)
        self.assertEqual(ticket.status, "in_progress")
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://ntfy.sh/test-topic")
        self.assertIn(ticket.title, kwargs["headers"]["Title"])

    @patch("ops.tasks.time.sleep")
    @patch("ops.tasks.requests.post")
    @patch("ops.tasks.NTFY_TOPIC", "")
    @patch("ops.tasks._localstack_reachable", return_value=False)
    @patch("ops.tasks._docker_reachable", return_value=False)
    @patch("ops.tasks._within_shift_hours", return_value=True)
    @patch("ops.tasks.random.random", return_value=0.0)
    def test_maybe_page_oncall_fires_silently_without_ntfy_topic_configured(
        self, mock_random, mock_shift, mock_docker, mock_localstack, mock_post, mock_sleep
    ):
        result = tasks.maybe_page_oncall()

        self.assertIsNotNone(result)
        mock_post.assert_not_called()
        mock_sleep.assert_not_called()

    def test_acknowledge_action_stops_escalation_signal(self):
        """The acknowledge API action itself — the loop-stopping side effect
        is exercised above via the mocked escalation test."""
        ticket = Ticket.objects.create(title="paged", fault_key="stuck_review", status="open")
        client = APIClient()

        response = client.post(f"/api/tickets/{ticket.id}/acknowledge/")

        self.assertEqual(response.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "in_progress")

    def test_acknowledge_is_idempotent_for_already_resolved_ticket(self):
        ticket = Ticket.objects.create(title="paged", status="resolved")
        client = APIClient()

        response = client.post(f"/api/tickets/{ticket.id}/acknowledge/")

        self.assertEqual(response.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "resolved")


class CloseTicketReplenishmentTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("ops.tasks.replenish_ticket.delay")
    def test_closing_a_ticket_triggers_replenishment(self, mock_delay):
        ticket = Ticket.objects.create(title="t", fault_key="llm_degraded", status="resolved")

        response = self.client.post(f"/api/tickets/{ticket.id}/close/")

        self.assertEqual(response.status_code, 200)
        mock_delay.assert_called_once()
