from collections import Counter

from avitotask.models import AvitoListing


def build_avito_listing_unmapped_summary(*, workspace, avito_account, limit=100):
    if avito_account.workspace_id != workspace.id:
        raise ValueError("Avito-аккаунт не принадлежит текущему кабинету.")

    queryset = (
        AvitoListing.objects
        .filter(
            workspace=workspace,
            avito_account=avito_account,
            source=AvitoListing.Source.AVITO_EXCEL,
        )
        .exclude(unmapped_data={})
        .values_list("unmapped_data", flat=True)
    )

    counter = Counter()
    listings_with_unmapped = 0

    for unmapped_data in queryset.iterator(chunk_size=1000):
        if not isinstance(unmapped_data, dict) or not unmapped_data:
            continue

        listings_with_unmapped += 1

        for column_name in unmapped_data.keys():
            counter[str(column_name)] += 1

    columns = [
        {
            "name": name,
            "count": count,
        }
        for name, count in counter.most_common(limit)
    ]

    return {
        "total_listings_with_unmapped": listings_with_unmapped,
        "total_columns": len(counter),
        "columns": columns,
    }
