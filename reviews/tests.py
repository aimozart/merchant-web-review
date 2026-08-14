from unittest.mock import MagicMock, patch

import requests
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from ops.models import OpsFlag
from reviews.llm import AnalysisResult, SignalResult, _rule_based_fallback, analyze
from reviews.models import Merchant, RiskSignal, WebPresenceReview
from reviews.scraping import WebPresenceSnapshot, gather_web_presence
from reviews.tasks import run_web_presence_review


class MerchantModelTests(TestCase):
    def test_str(self):
        merchant = Merchant.objects.create(
            business_name="Acme Co", website_url="https://acme.example"
        )
        self.assertIn("Acme Co", str(merchant))

    def test_deleting_merchant_cascades_to_reviews_and_signals(self):
        merchant = Merchant.objects.create(
            business_name="Acme Co", website_url="https://acme.example"
        )
        review = WebPresenceReview.objects.create(merchant=merchant, status="complete")
        RiskSignal.objects.create(review=review, category="domain", label="x")

        merchant.delete()

        self.assertFalse(WebPresenceReview.objects.filter(id=review.id).exists())
        self.assertFalse(RiskSignal.objects.filter(review_id=review.id).exists())


class ScrapingTests(TestCase):
    @patch("reviews.scraping.requests.get")
    @patch("reviews.scraping.socket.gethostbyname", return_value="93.184.216.34")
    def test_extracts_title_social_links_and_keyword_hits(self, mock_dns, mock_get):
        html = """
        <html><head><title>Acme Shop</title>
        <meta name="description" content="We sell things"></head>
        <body>
          <a href="https://facebook.com/acmeshop">Follow us</a>
          <p>Guaranteed returns on every replica watches purchase!</p>
        </body></html>
        """
        mock_get.return_value = MagicMock(status_code=200, text=html)

        snapshot = gather_web_presence("https://acme.example")

        self.assertEqual(snapshot.status_code, 200)
        self.assertEqual(snapshot.title, "Acme Shop")
        self.assertEqual(snapshot.meta_description, "We sell things")
        self.assertEqual(snapshot.resolved_ip, "93.184.216.34")
        self.assertIn("https://facebook.com/acmeshop", snapshot.social_links)
        self.assertIn("guaranteed returns", snapshot.prohibited_keyword_hits)
        self.assertIn("replica watches", snapshot.prohibited_keyword_hits)

    @patch("reviews.scraping.requests.get", side_effect=requests.ConnectionError("refused"))
    def test_records_fetch_error_without_raising(self, mock_get):
        snapshot = gather_web_presence("https://unreachable.invalid")

        self.assertIsNotNone(snapshot.fetch_error)
        self.assertEqual(snapshot.status_code, None)


def _snapshot(**overrides) -> WebPresenceSnapshot:
    defaults = dict(url="https://acme.example", fetched_at="2026-01-01T00:00:00")
    defaults.update(overrides)
    return WebPresenceSnapshot(**defaults)


class RuleBasedFallbackTests(TestCase):
    def test_fetch_error_recommends_review(self):
        result = _rule_based_fallback(_snapshot(fetch_error="timed out"))
        self.assertEqual(result.recommendation, "review")
        self.assertTrue(any(s.category == "domain" for s in result.signals))

    def test_prohibited_keyword_recommends_fail(self):
        result = _rule_based_fallback(_snapshot(prohibited_keyword_hits=["escort"]))
        self.assertEqual(result.recommendation, "fail")
        self.assertTrue(any(s.severity == "high" for s in result.signals))

    def test_reputation_keyword_recommends_review(self):
        result = _rule_based_fallback(
            _snapshot(resolved_ip="1.2.3.4", reputation_keyword_hits=["scam"])
        )
        self.assertEqual(result.recommendation, "review")

    def test_clean_site_recommends_pass(self):
        result = _rule_based_fallback(
            _snapshot(resolved_ip="1.2.3.4", social_links=["https://facebook.com/acme"])
        )
        self.assertEqual(result.recommendation, "pass")

    def test_no_social_presence_is_low_severity_not_disqualifying(self):
        result = _rule_based_fallback(_snapshot(resolved_ip="1.2.3.4"))
        self.assertEqual(result.recommendation, "pass")
        social_signals = [s for s in result.signals if s.category == "social"]
        self.assertEqual(social_signals[0].severity, "low")


class AnalyzeEntryPointTests(TestCase):
    def test_falls_back_when_no_api_key_configured(self):
        with override_settings():
            result = analyze(_snapshot(resolved_ip="1.2.3.4"), "Acme")
        self.assertIsInstance(result, AnalysisResult)

    @patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"})
    def test_llm_disabled_flag_forces_rule_based_path_even_with_key_set(self):
        OpsFlag.set_flag("llm_analysis_disabled", True)
        with patch("reviews.llm._llm_analyze") as mock_llm:
            result = analyze(_snapshot(resolved_ip="1.2.3.4"), "Acme")
        mock_llm.assert_not_called()
        self.assertIsInstance(result, AnalysisResult)

    @patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"})
    def test_llm_exception_falls_back_to_rule_based(self):
        OpsFlag.objects.all().delete()
        with patch("reviews.llm._llm_analyze", side_effect=RuntimeError("boom")):
            result = analyze(_snapshot(resolved_ip="1.2.3.4"), "Acme")
        self.assertIsInstance(result, AnalysisResult)


class RunWebPresenceReviewTaskTests(TestCase):
    def setUp(self):
        self.merchant = Merchant.objects.create(
            business_name="Acme Co", website_url="https://acme.example"
        )
        self.review = WebPresenceReview.objects.create(merchant=self.merchant)

    @patch("reviews.tasks.analyze")
    @patch("reviews.tasks.storage.store_snapshot", return_value="reviews/abc/snapshot.json")
    @patch("reviews.tasks.gather_web_presence")
    def test_successful_review_completes_and_stores_signals(
        self, mock_gather, mock_store, mock_analyze
    ):
        mock_gather.return_value = _snapshot(resolved_ip="1.2.3.4")
        mock_analyze.return_value = AnalysisResult(
            recommendation="pass",
            summary="Looks fine.",
            signals=[SignalResult(category="domain", severity="info", label="ok")],
        )

        run_web_presence_review.apply(args=[str(self.review.id)])

        self.review.refresh_from_db()
        self.assertEqual(self.review.status, "complete")
        self.assertEqual(self.review.recommendation, "pass")
        self.assertEqual(self.review.snapshot_object_key, "reviews/abc/snapshot.json")
        self.assertEqual(self.review.signals.count(), 1)
        self.assertIsNotNone(self.review.completed_at)

    @patch("reviews.tasks.gather_web_presence", side_effect=RuntimeError("scrape exploded"))
    def test_exhausting_retries_marks_review_failed(self, mock_gather):
        run_web_presence_review.apply(args=[str(self.review.id)])

        self.review.refresh_from_db()
        self.assertEqual(self.review.status, "failed")
        self.assertIn("scrape exploded", self.review.error_message)


class MerchantApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("reviews.views.run_web_presence_review.delay")
    def test_create_merchant_queues_a_review(self, mock_delay):
        response = self.client.post(
            "/api/merchants/",
            {"business_name": "Acme Co", "website_url": "https://acme.example"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        merchant = Merchant.objects.get(business_name="Acme Co")
        self.assertEqual(WebPresenceReview.objects.filter(merchant=merchant).count(), 1)
        mock_delay.assert_called_once()

    @patch("reviews.views.run_web_presence_review.delay")
    def test_monitoring_action_updates_merchant(self, mock_delay):
        merchant = Merchant.objects.create(
            business_name="Acme Co", website_url="https://acme.example"
        )

        response = self.client.post(
            f"/api/merchants/{merchant.id}/monitoring/",
            {"enabled": True, "interval_hours": 6},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        merchant.refresh_from_db()
        self.assertTrue(merchant.monitoring_enabled)
        self.assertEqual(merchant.monitoring_interval_hours, 6)

    @patch("reviews.views.run_web_presence_review.delay")
    def test_rereview_action_queues_new_review(self, mock_delay):
        merchant = Merchant.objects.create(
            business_name="Acme Co", website_url="https://acme.example"
        )

        response = self.client.post(f"/api/merchants/{merchant.id}/rereview/", format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(WebPresenceReview.objects.filter(merchant=merchant).count(), 1)
        mock_delay.assert_called_once()
