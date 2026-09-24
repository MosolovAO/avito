from rest_framework.routers import SimpleRouter

from automations.api_views import AutomationViewSet


router = SimpleRouter()
router.register(
    "",
    AutomationViewSet,
    basename="automation",
)

urlpatterns = router.urls