from datetime import timedelta
from django.utils import timezone
from rest_framework import serializers

AVITO_STATS_SYNC_MAX_PERIOD_DAYS = 270
AVITO_LISTING_STATS_MAX_PERIOD_DAYS = 270


class AvitoAccountImportDailyStatsSerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    listing_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=False,
    )

    def validate(self, attrs):
        date_from = attrs.get("date_from")
        date_to = attrs.get("date_to")

        if (date_from is None) != (date_to is None):
            raise serializers.ValidationError({
                "date_to": (
                    "date_from и date_to должны быть переданы вместе."
                )
            })

        if date_from is None:
            return attrs

        if date_from > date_to:
            raise serializers.ValidationError({
                "date_to": (
                    "date_to должен быть больше или равен date_from."
                )
            })

        last_completed_date = (
                timezone.localdate() - timedelta(days=1)
        )

        if date_to > last_completed_date:
            raise serializers.ValidationError({
                "date_to": (
                    "Можно синхронизировать только полностью "
                    "завершённые дни."
                )
            })

        period_days = (date_to - date_from).days + 1

        if period_days > AVITO_STATS_SYNC_MAX_PERIOD_DAYS:
            raise serializers.ValidationError({
                "date_from": (
                    "Период синхронизации не может превышать "
                    f"{AVITO_STATS_SYNC_MAX_PERIOD_DAYS} дней."
                )
            })

        return attrs


class AvitoListingStatsQuerySerializer(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()
    listing_ids = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    page = serializers.IntegerField(
        required=False,
        default=1,
        min_value=1,
    )
    page_size = serializers.IntegerField(
        required=False,
        default=50,
        min_value=1,
        max_value=50,
    )

    def validate(self, attrs):
        date_from = attrs["date_from"]
        date_to = attrs["date_to"]

        if date_from > date_to:
            raise serializers.ValidationError({
                "date_to": (
                    "date_to должен быть больше или равен date_from."
                )
            })

        last_completed_date = (
                timezone.localdate() - timedelta(days=1)
        )

        if date_to > last_completed_date:
            raise serializers.ValidationError({
                "date_to": (
                    "Можно запрашивать только полностью "
                    "завершённые дни."
                )
            })

        period_days = (date_to - date_from).days + 1

        if period_days > AVITO_LISTING_STATS_MAX_PERIOD_DAYS:
            raise serializers.ValidationError({
                "date_from": (
                    "Период отчёта не может превышать "
                    f"{AVITO_LISTING_STATS_MAX_PERIOD_DAYS} дней."
                )
            })

        attrs["listing_ids"] = parse_listing_ids(
            attrs.get("listing_ids")
        )
        return attrs


def parse_listing_ids(value):
    if not value:
        return None

    listing_ids = []

    for raw_id in value.split(","):
        raw_id = raw_id.strip()

        if not raw_id:
            continue

        if not raw_id.isdigit():
            raise serializers.ValidationError(
                "listing_ids должен быть списком id через запятую."
            )

        listing_ids.append(int(raw_id))

    return listing_ids or None
