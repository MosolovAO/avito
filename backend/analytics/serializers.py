from rest_framework import serializers


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

        if (
            date_from is not None
            and date_to is not None
            and date_from > date_to
        ):
            raise serializers.ValidationError({
                "date_to": (
                    "date_to должен быть больше или равен date_from."
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

    def validate(self, attrs):
        if attrs["date_from"] > attrs["date_to"]:
            raise serializers.ValidationError({
                "date_to": (
                    "date_to должен быть больше или равен date_from."
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