import type {JsonObject} from "../../../entities/avito/types";
import type {ProductOption} from "../../../entities/product";

export type EditableOptionValue = string | string[];

const HIDDEN_BASE_DATA_KEYS = new Set(["Category", "Price"]);

export const getCreativeAutoloadCategory = (
    baseData: JsonObject,
): string => {
    const category = baseData.Category;

    return typeof category === "string"
        ? category.trim()
        : "";
};

export const getCreativePrice = (baseData: JsonObject): number | undefined => {
    const price = baseData.Price;

    if (typeof price === "number") {
        return price;
    }

    if (typeof price === "string") {
        const normalizedPrice = Number(price.replace(",", "."));

        return Number.isFinite(normalizedPrice) ? normalizedPrice : undefined;
    }

    return undefined;
};

export const buildBaseDataFormValues = (
    baseData: JsonObject,
): Record<string, string> => {
    return Object.entries(baseData).reduce<Record<string, string>>((acc, [key, value]) => {
        if (HIDDEN_BASE_DATA_KEYS.has(key)) {
            return acc;
        }

        if (value === null || value === undefined) {
            acc[key] = "";
            return acc;
        }

        acc[key] = String(value);
        return acc;
    }, {});
};

export const buildBaseData = (
    currentBaseData: JsonObject,
    formBaseData: Record<string, string | undefined>,
    price: number,
    autoloadCategory: string,
): JsonObject => {
    const normalizedAutoloadCategory = autoloadCategory.trim();

    return Object.entries(formBaseData).reduce<JsonObject>(
        (acc, [key, value]) => {
            if (HIDDEN_BASE_DATA_KEYS.has(key)) {
                return acc;
            }

            acc[key] = value?.trim() ?? "";
            return acc;
        },
        {
            ...currentBaseData,
            Category: normalizedAutoloadCategory,
            Price: price,
        },
    );
};

const normalizeSingleOptionValue = (value: unknown): string => {
    if (Array.isArray(value)) {
        const firstValue = value.find((item) => String(item).trim());

        return firstValue === undefined ? "" : String(firstValue).trim();
    }

    return value === undefined || value === null ? "" : String(value).trim();
};

const normalizeMultipleOptionValue = (value: unknown): string[] => {
    if (Array.isArray(value)) {
        return value.map((item) => String(item).trim()).filter(Boolean);
    }

    const normalized = value === undefined || value === null ? "" : String(value).trim();

    return normalized ? [normalized] : [];
};

export const buildOptionFormValues = (
    optionData: JsonObject,
    productOptions: ProductOption[],
): Record<string, EditableOptionValue> => {
    return productOptions.reduce<Record<string, EditableOptionValue>>((acc, option) => {
        const optionKey = option.option_title_en;
        const value = optionData[optionKey];
        const allowMultiple = option.allow_multiple ?? option.allow_multiple_options;

        acc[String(option.id)] = allowMultiple
            ? normalizeMultipleOptionValue(value)
            : normalizeSingleOptionValue(value);

        return acc;
    }, {});
};

export const buildOptionData = (
    selectedOptions: Record<string, EditableOptionValue | undefined>,
    productOptions: ProductOption[],
): JsonObject => {
    return productOptions.reduce<JsonObject>((acc, option) => {
        const value = selectedOptions[String(option.id)];
        const allowMultiple = option.allow_multiple ?? option.allow_multiple_options;

        if (allowMultiple) {
            const values = Array.isArray(value)
                ? value.map((item) => item.trim()).filter(Boolean)
                : normalizeMultipleOptionValue(value);

            acc[option.option_title_en] = values;
            return acc;
        }

        acc[option.option_title_en] = normalizeSingleOptionValue(value);
        return acc;
    }, {});
};

export const mergeUnknownOptionData = (
    currentOptionData: JsonObject,
    nextOptionData: JsonObject,
    productOptions: ProductOption[],
): JsonObject => {
    const knownOptionKeys = new Set(
        productOptions.map((option) => option.option_title_en),
    );

    return Object.entries(currentOptionData).reduce<JsonObject>(
        (acc, [key, value]) => {
            if (!knownOptionKeys.has(key)) {
                acc[key] = value;
            }

            return acc;
        },
        {...nextOptionData},
    );
};

export const parseClearOverrideFields = (value?: string): string[] | undefined => {
    const fields = (value ?? "")
        .split(",")
        .map((field) => field.trim())
        .filter(Boolean);

    return fields.length > 0 ? fields : undefined;
};
