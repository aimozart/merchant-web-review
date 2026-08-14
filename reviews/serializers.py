from rest_framework import serializers

from .models import Merchant, RiskSignal, WebPresenceReview


class RiskSignalSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskSignal
        fields = ["id", "category", "severity", "label", "detail"]


class WebPresenceReviewSerializer(serializers.ModelSerializer):
    signals = RiskSignalSerializer(many=True, read_only=True)

    class Meta:
        model = WebPresenceReview
        fields = [
            "id",
            "status",
            "is_monitoring_check",
            "recommendation",
            "summary",
            "error_message",
            "created_at",
            "completed_at",
            "signals",
        ]


class MerchantSerializer(serializers.ModelSerializer):
    latest_review = serializers.SerializerMethodField()

    class Meta:
        model = Merchant
        fields = [
            "id",
            "business_name",
            "website_url",
            "created_at",
            "monitoring_enabled",
            "monitoring_interval_hours",
            "latest_review",
        ]

    def get_latest_review(self, obj):
        review = obj.reviews.order_by("-created_at").first()
        return WebPresenceReviewSerializer(review).data if review else None


class CreateMerchantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Merchant
        fields = ["business_name", "website_url"]
