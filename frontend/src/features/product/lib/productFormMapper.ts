import type {ProductFormData, ProductOptionValue, ProductImageValue} from "../../../entities/product";

export type ProductFormValues = Omit<
    ProductFormData,
    'options' | 'main_images' | 'additional_images'
> & {
    options?: Record<string, ProductOptionValue | undefined>
    main_images?: ProductImageValue[]
    additional_images?: ProductImageValue[]
}

interface BuildProductFormDataParams {
    mainImages: string[]
    additionalImages: string[]
}

export const normalizeCategory = (category: string | undefined): string =>
    category?.trim() ?? ''

const normalizeStringList = (values: string[] | undefined): string[] =>
    values?.map((value) => value.trim()).filter(Boolean) ?? []

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
    price_randomization_enabled: data?.price_randomization_enabled ?? false,
    titles: normalizeStringList(data?.titles),
    descriptions: data?.descriptions?.length ? data.descriptions : [''],
    addresses: normalizeStringList(data?.addresses),
    main_images: data?.main_images ?? [],
    additional_images: data?.additional_images ?? [],
    options: data?.options?.reduce<Record<string, ProductOptionValue | undefined>>((acc, option) => {
        acc[String(option.option_id)] = option.value
        return acc
    }, {}),
    schedule: {
        frequency: data?.schedule?.frequency ?? 1,
        days: data?.schedule?.days ?? [],
    },
})


export const buildProductFormData = (values: ProductFormValues, images: BuildProductFormDataParams): ProductFormData => {
    const randomizationEnabled = Boolean(values.price_randomization_enabled)

    const options = Object.entries(values.options ?? {}).flatMap(([optionId, value]) => {
        const normalizedValue = normalizeOptionValue(value)

        if (normalizedValue === undefined) {
            return []
        }

        return [{
            option_id: Number(optionId),
            value: normalizedValue,
        }]
    })

    return {
        ...values,
        price_randomization_enabled: randomizationEnabled,
        titles: normalizeStringList(values.titles),
        descriptions: normalizeStringList(values.descriptions),
        addresses: normalizeStringList(values.addresses),
        main_images: images.mainImages,
        additional_images: images.additionalImages,
        options,
        price_min: randomizationEnabled ? values.price_min : 0,
        price_max: randomizationEnabled ? values.price_max : 0,
        price_step: randomizationEnabled ? values.price_step : 0,
    }
}
