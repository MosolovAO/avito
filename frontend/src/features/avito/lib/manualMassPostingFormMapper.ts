// src/features/avito/lib/manualMassPostingFormMapper.ts
import type {CreateManualMassPostingRequest, JsonObject} from "../../../entities/avito/types";
import type {ProductOption, ProductOptionValue} from "../../../entities/product";

export interface ManualMassPostingFormValues {
    option_category_id: number;
    autoload_category: string;
    avito_account_ids: number[];
    title: string;
    description: string;
    price: number;
    addresses?: string[];
    options?: Record<string, ProductOptionValue | undefined>;
    email?: string;
    contactphone?: string;
    managername?: string;
    companyname?: string;
    listingfee?: string;
    avitostatus?: string;
    contactmethod?: string;
    adtype?: string;
    availability?: string;
}

interface BuildManualMassPostingRequestParams {
    imageUrls: string[];
    productOptions: ProductOption[];
}

const normalizeString = (value: string | undefined): string => value?.trim() ?? "";

const normalizeStringList = (values: string[] | undefined): string[] =>
    values?.map((value) => value.trim()).filter(Boolean) ?? [];

const normalizeOptionValue = (
    value: ProductOptionValue | undefined,
): ProductOptionValue | undefined => {
    if (Array.isArray(value)) {
        const normalized = value.map((item) => item.trim()).filter(Boolean);

        return normalized.length > 0 ? normalized : undefined;
    }

    const normalized = value?.trim();

    return normalized ? normalized : undefined;
};

const addOptionalStringField = (
    target: JsonObject,
    key: string,
    value: string | undefined,
): void => {
    const normalized = normalizeString(value);

    if (normalized) {
        target[key] = normalized;
    }
};

export const buildManualPostingBaseData = (values: ManualMassPostingFormValues): JsonObject => {
    const baseData: JsonObject = {
        Category: normalizeString(values.autoload_category),
        Price: values.price,
    };

    addOptionalStringField(baseData, "EMail", values.email);
    addOptionalStringField(baseData, "ContactPhone", values.contactphone);
    addOptionalStringField(baseData, "ManagerName", values.managername);
    addOptionalStringField(baseData, "CompanyName", values.companyname);
    addOptionalStringField(baseData, "ListingFee", values.listingfee);
    addOptionalStringField(baseData, "AvitoStatus", values.avitostatus);
    addOptionalStringField(baseData, "ContactMethod", values.contactmethod);
    addOptionalStringField(baseData, "AdType", values.adtype);
    addOptionalStringField(baseData, "Availability", values.availability);

    return baseData;
};

export const buildManualPostingOptionData = (
    selectedOptions: ManualMassPostingFormValues["options"],
    productOptions: ProductOption[],
): JsonObject => {
    const optionsById = new Map(
        productOptions.map((option) => [String(option.id), option.option_title_en]),
    );

    return Object.entries(selectedOptions ?? {}).reduce<JsonObject>((acc, [optionId, value]) => {
        const optionKey = optionsById.get(optionId);
        const normalizedValue = normalizeOptionValue(value);

        if (!optionKey || normalizedValue === undefined) {
            return acc;
        }

        acc[optionKey] = normalizedValue;

        return acc;
    }, {});
};

export const buildManualMassPostingRequest = (
    values: ManualMassPostingFormValues,
    {imageUrls, productOptions}: BuildManualMassPostingRequestParams,
): CreateManualMassPostingRequest => ({
    option_category_id: values.option_category_id,
    avito_account_ids: values.avito_account_ids,
    title: normalizeString(values.title),
    description: normalizeString(values.description),
    addresses: normalizeStringList(values.addresses),
    image_urls: normalizeStringList(imageUrls),
    base_data: buildManualPostingBaseData(values),
    option_data: buildManualPostingOptionData(
        values.options,
        productOptions,
    ),
});
