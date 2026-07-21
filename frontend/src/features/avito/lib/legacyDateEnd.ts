import type {JsonObject} from "../../../entities/avito/types";

export const isLegacyDateEndKey = (key: string): boolean =>
    key === "DateEnd" || key === "date_end";

export const withoutLegacyDateEnd = (
    value: JsonObject,
): JsonObject =>
    Object.entries(value).reduce<JsonObject>((result, [key, item]) => {
        if (!isLegacyDateEndKey(key)) {
            result[key] = item;
        }

        return result;
    }, {});