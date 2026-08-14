from rest_framework.routers import DefaultRouter

from .views import MerchantViewSet

router = DefaultRouter()
router.register("merchants", MerchantViewSet, basename="merchant")

urlpatterns = router.urls
