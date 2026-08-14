from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Merchant, WebPresenceReview
from .serializers import (
    CreateMerchantSerializer,
    MerchantSerializer,
    WebPresenceReviewSerializer,
)
from .tasks import run_web_presence_review


class MerchantViewSet(viewsets.ModelViewSet):
    """
    Submit a merchant for a Web Presence Review, list past merchants/reviews, and
    toggle Merchant Monitoring — the two core product surfaces TrueBiz's own site
    describes (initial review + ongoing monitoring).
    """

    queryset = Merchant.objects.order_by("-created_at")
    serializer_class = MerchantSerializer

    def get_serializer_class(self):
        if self.action == "create":
            return CreateMerchantSerializer
        return MerchantSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        merchant = serializer.save()

        review = WebPresenceReview.objects.create(merchant=merchant)
        run_web_presence_review.delay(str(review.id))

        return Response(MerchantSerializer(merchant).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def rereview(self, request, pk=None):
        """Manually trigger a fresh Web Presence Review for an existing merchant."""
        merchant = self.get_object()
        review = WebPresenceReview.objects.create(merchant=merchant)
        run_web_presence_review.delay(str(review.id))
        return Response(WebPresenceReviewSerializer(review).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def monitoring(self, request, pk=None):
        """Enable/disable Merchant Monitoring (periodic re-checks) for a merchant."""
        merchant = self.get_object()
        enabled = bool(request.data.get("enabled", True))
        interval = int(request.data.get("interval_hours", merchant.monitoring_interval_hours))
        merchant.monitoring_enabled = enabled
        merchant.monitoring_interval_hours = interval
        merchant.save(update_fields=["monitoring_enabled", "monitoring_interval_hours"])
        return Response(MerchantSerializer(merchant).data)

    @action(detail=True, methods=["get"])
    def reviews(self, request, pk=None):
        merchant = self.get_object()
        qs = merchant.reviews.order_by("-created_at")
        return Response(WebPresenceReviewSerializer(qs, many=True).data)
