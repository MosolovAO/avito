import type {
    ProductFormData,
    ProductOptionValue,
    ProductImageValue,
} from "../../../entities/product";

import type {ProductSchedule} from "../../../entities/product/types";

export type ProductFormValues = Omit<
    ProductFormData,
    "options" | "main_images" | "additional_images"
> & {
    autoload_category?: string
    options?: Record<string, ProductOptionValue | undefined>
    main_images?: ProductImageValue[]
    additional_images?: ProductImageValue[]
}

interface BuildProductFormDataParams {
    mainImages: string[]
    additionalImages: string[]
    mainImageAssetIds: number[]
    additionalImageAssetIds: number[]
}

type ScheduleDaysValue =
    | ProductSchedule['days']
    | Record<string, string | null | undefined>

const SCHEDULE_DAYS_COUNT = 7

export const normalizeCategory = (category: string | undefined): string =>
    category?.trim() ?? ''

const normalizeStringList = (values: string[] | undefined): string[] =>
    values?.map((value) => value.trim()).filter(Boolean) ?? []

const normalizeScheduleDays = (
    days: ScheduleDaysValue | undefined
): ProductSchedule['days'] => {
    const normalizedDays: ProductSchedule['days'] = Array.from(
        {length: SCHEDULE_DAYS_COUNT},
        () => null
    )

    if (Array.isArray(days)) {
        return normalizedDays.map((_, index) => days[index] ?? null)
    }

    if (days && typeof days === 'object') {
        Object.entries(days).forEach(([key, value]) => {
            const index = Number(key)

            if (Number.isInteger(index) && index >= 0 && index < SCHEDULE_DAYS_COUNT) {
                normalizedDays[index] = value ?? null
            }
        })
    }

    return normalizedDays
}

const buildBaseData = (
    values: ProductFormValues,
): ProductFormData["base_data"] => ({
    Category: normalizeCategory(values.autoload_category),
    ListingFee: values.listingfee,
    EMail: values.email,
    ContactPhone: values.contactphone,
    ManagerName: values.managername,
    AvitoStatus: values.avitostatus,
    CompanyName: values.companyname,
    ContactMethod: values.contactmethod,
    AdType: values.adtype,
    Availability: values.availability,
});

const toImageValues = (
    urls: string[] | undefined,
    ids: number[] | undefined
): ProductImageValue[] =>
    (urls ?? []).map((url, index) => {
        const id = ids?.[index]
        return id ? {id, url} : url
    })

const normalizeOptionValue = (
    value: ProductOptionValue | undefined
): ProductOptionValue | undefined => {
    if (Array.isArray(value)) {
        const normalized = value.map((item) => item.trim()).filter(Boolean)
        return normalized.length > 0 ? normalized : undefined
    }

    const normalized = value?.trim()
    return normalized ? normalized : undefined
}

export const createProductInitialValues = (
    data?: Partial<ProductFormData>
): Partial<ProductFormValues> => ({
    ...data,
    name: data?.name ?? '',
    autoload_category: data?.base_data?.Category ?? "",
    avito_account_ids: data?.avito_account_ids ?? [],
    price_randomization_enabled: data?.price_randomization_enabled ?? false,
    titles: normalizeStringList(data?.titles),
    descriptions: data?.descriptions?.length ? data.descriptions : [''],
    addresses: normalizeStringList(data?.addresses),
    main_images: toImageValues(data?.main_images, data?.main_image_asset_ids),
    additional_images: toImageValues(data?.additional_images, data?.additional_image_asset_ids),
    options: data?.options?.reduce<Record<string, ProductOptionValue | undefined>>((acc, option) => {
        acc[String(option.option_id)] = option.value
        return acc
    }, {}),
    schedule: {
        frequency: data?.schedule?.frequency ?? 1,
        days: normalizeScheduleDays(data?.schedule?.days),
    },
})


export const buildProductFormData = (
    values: ProductFormValues,
    images: BuildProductFormDataParams,
): ProductFormData => {
    const randomizationEnabled = Boolean(values.price_randomization_enabled);

    const requestValues = {...values};
    delete requestValues.autoload_category;
    const options = Object.entries(values.options ?? {}).flatMap(([optionId, value]) => {
        const normalizedValue = normalizeOptionValue(value)
        return normalizedValue === undefined ? [] : [{
            option_id: Number(optionId),
            value: normalizedValue,
        }]
    })

    return {
        ...requestValues,
        base_data: buildBaseData(values),
        price_randomization_enabled: randomizationEnabled,
        titles: normalizeStringList(values.titles),
        descriptions: normalizeStringList(values.descriptions),
        addresses: normalizeStringList(values.addresses),
        main_images: images.mainImages,
        additional_images: images.additionalImages,
        main_image_asset_ids: images.mainImageAssetIds,
        additional_image_asset_ids: images.additionalImageAssetIds,
        options,
        schedule: {
            frequency: values.schedule?.frequency ?? 1,
            days: normalizeScheduleDays(values.schedule?.days),
        },
        price_min: randomizationEnabled ? values.price_min : 0,
        price_max: randomizationEnabled ? values.price_max : 0,
        price_step: randomizationEnabled ? values.price_step : 0,
    }
}
