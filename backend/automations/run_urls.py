from rest_framework.routers import SimpleRouter

from automations.api_views import AutomationRunViewSet


router = SimpleRouter()
router.register(
    "",
    AutomationRunViewSet,
    basename="automation-run",
)

urlpatterns = router.urls