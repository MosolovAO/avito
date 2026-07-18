import logging

from celery import shared_task

from avitotask.models import AvitoAccount
from analytics.services.avito_stats import import_avito_listing_daily_stats_for_account

logger = logging.getLogger(__name__)


@shared_task
def import_avito_account_daily_stats_task(
        avito_account_id,
        date_from,
        date_to,
        listing_ids=None,
        session=None,
):
    avito_account = (
        AvitoAccount.objects
        .select_related("workspace")
        .get(id=avito_account_id)
    )

    result = import_avito_listing_daily_stats_for_account(
        avito_account=avito_account,
        date_from=date_from,
        date_to=date_to,
        listing_ids=listing_ids,
        session=session,
    )

    logger.info(
        "Imported Avito daily stats for account_id=%s: listings=%s days=%s created=%s updated=%s",
        avito_account.id,
        result.total_listings,
        result.total_days,
        result.created_stats,
        result.updated_stats,
    )

    return {
        "total_listings": result.total_listings,
        "total_days": result.total_days,
        "created_stats": result.created_stats,
        "updated_stats": result.updated_stats,
    }
