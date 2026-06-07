import type {
    AdPublicationStatus,
    AvitoAccountAd,
    JsonObject,
    UpdateAdPublicationRequest,
} from "../../../entities/avito/types";

export interface PublicationEditFormValues {
    title: string;
    description: string;
    address: string;
    status: AdPublicationStatus;
    image_urls_text: string;
    base_data_json: string;
    option_data_json: string;
}

const publicationStatuses: AdPublicationStatus[] = [
    "draft",
    "active",
    "paused",
    "archived",
    "error",
];

const imageUrlsSeparator = " | ";

const hasOwn = (value: JsonObject, key: string): boolean =>
    Object.prototype.hasOwnProperty.call(value, key);

const isPublicationStatus = (value: string | null): value is AdPublicationStatus =>
    publicationStatuses.includes(value as AdPublicationStatus);

const stringifyJsonForForm = (value: JsonObject): string =>
    JSON.stringify(value ?? {}, null, 2);

const areJsonValuesEqual = (left: unknown, right: unknown): boolean =>
    JSON.stringify(left) === JSON.stringify(right);

const getStringOverride = (
    overrides: JsonObject,
    key: string,
): string | undefined => {
    const value = overrides[key];

    return typeof value === "string" ? value : undefined;
};

const parseJsonObject = (value: string, fieldLabel: string): JsonObject => {
    const parsed = JSON.parse(value || "{}");

    if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") {
        throw new Error(`${fieldLabel} должен быть JSON-объектом`);
    }

    return parsed as JsonObject;
};

const parseImageUrls = (value: string): string[] =>
    value
        .split(/\r?\n/)
        .map((item) => item.trim())
        .filter(Boolean);

const parseStoredImageUrlsOverride = (value: unknown): string[] | null => {
    if (typeof value === "string") {
        return value
            .split(/\s*\|\s*|\r?\n/)
            .map((item) => item.trim())
            .filter(Boolean);
    }

    if (Array.isArray(value)) {
        return value
            .map((item) => String(item).trim())
            .filter(Boolean);
    }

    return null;
};

const mergeKnownOverrides = (
    inheritedData: JsonObject,
    overrides: JsonObject,
): JsonObject => {
    const result: JsonObject = {...inheritedData};

    Object.keys(inheritedData).forEach((key) => {
        if (hasOwn(overrides, key)) {
            result[key] = overrides[key];
        }
    });

    return result;
};

export const buildPublicationEditInitialValues = (
    item: AvitoAccountAd,
    overrides: JsonObject,
): PublicationEditFormValues => {
    const imageUrlsOverride = parseStoredImageUrlsOverride(overrides.ImageUrls);

    return {
        title: getStringOverride(overrides, "Title") ?? item.title ?? "",
        description: getStringOverride(overrides, "Description") ?? item.description ?? "",
        address: item.address,
        status: isPublicationStatus(item.status) ? item.status : "draft",
        image_urls_text: (imageUrlsOverride ?? item.image_urls).join("\n"),
        base_data_json: stringifyJsonForForm(
            mergeKnownOverrides(item.base_data, overrides),
        ),
        option_data_json: stringifyJsonForForm(
            mergeKnownOverrides(item.option_data, overrides),
        ),
    };
};

export const buildPublicationUpdateRequest = (
    item: AvitoAccountAd,
    existingOverrides: JsonObject,
    values: PublicationEditFormValues,
): UpdateAdPublicationRequest => {
    const baseData = parseJsonObject(values.base_data_json, "base_data");
    const optionData = parseJsonObject(values.option_data_json, "option_data");
    const imageUrls = parseImageUrls(values.image_urls_text);
    const controlledKeys = new Set([
        "Title",
        "Description",
        "ImageUrls",
        ...Object.keys(item.base_data),
        ...Object.keys(item.option_data),
        ...Object.keys(baseData),
        ...Object.keys(optionData),
    ]);
    const nextOverrides: JsonObject = {};

    Object.entries(existingOverrides).forEach(([key, value]) => {
        if (!controlledKeys.has(key)) {
            nextOverrides[key] = value;
        }
    });

    if (values.title !== (item.title ?? "")) {
        nextOverrides.Title = values.title;
    }

    if (values.description !== (item.description ?? "")) {
        nextOverrides.Description = values.description;
    }

    if (!areJsonValuesEqual(imageUrls, item.image_urls)) {
        nextOverrides.ImageUrls = imageUrls.join(imageUrlsSeparator);
    }

    Object.entries(baseData).forEach(([key, value]) => {
        if (!areJsonValuesEqual(value, item.base_data[key])) {
            nextOverrides[key] = value;
        }
    });

    Object.entries(optionData).forEach(([key, value]) => {
        if (!areJsonValuesEqual(value, item.option_data[key])) {
            nextOverrides[key] = value;
        }
    });

    return {
        address: values.address.trim(),
        status: values.status,
        overrides: nextOverrides,
    };
};
