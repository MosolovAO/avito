import {isAxiosError} from "axios";

type BackendErrorValue = string | string[] | Record<string, unknown>;

interface BackendErrorPayload {
    detail?: BackendErrorValue;
    error?: BackendErrorValue;
    avito?: BackendErrorValue;
    non_field_errors?: BackendErrorValue;

    [key: string]: unknown;
}


const stringifyBackendValue = (value: BackendErrorValue): string => {
    if (typeof value === "string") {
        return value;
    }

    if (Array.isArray(value)) {
        return value.join(", ");
    }

    return Object.values(value)
        .flatMap((item) => (Array.isArray(item) ? item : [item]))
        .filter((item): item is string => typeof item === "string")
        .join(", ");
};
export const getApiErrorMessage = (
    error: unknown,
    fallback = "Не удалось выполнить запрос",
): string => {
    if (!isAxiosError<BackendErrorPayload | string>(error)) {
        return error instanceof Error ? error.message : fallback;
    }

    const data = error.response?.data;

    if (!data) {
        return fallback;
    }

    if (typeof data === "string") {
        return data.trim().startsWith("<") ? fallback : data;
    }

    const knownValue =
        data.detail ?? data.error ?? data.avito ?? data.non_field_errors;

    if (knownValue) {
        const message = stringifyBackendValue(knownValue);
        return message || fallback;
    }

    const firstFieldError = Object.values(data).find(
        (value): value is BackendErrorValue =>
            typeof value === "string" ||
            Array.isArray(value) ||
            (typeof value === "object" && value !== null),
    );

    return firstFieldError ? stringifyBackendValue(firstFieldError) : fallback;
};