const DATE_ONLY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export const formatDate = (
    value: string | null | undefined,
    fallback = "не указано",
): string => {
    if (!value) {
        return fallback;
    }

    if (DATE_ONLY_PATTERN.test(value)) {
        return value;
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return fallback;
    }

    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");

    return `${year}-${month}-${day}`;
};

export const formatDateTime = (
    value: string | null | undefined,
    fallback = "не было",
): string => {
    if (!value) {
        return fallback;
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return fallback;
    }

    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    const hours = String(date.getHours()).padStart(2, "0");
    const minutes = String(date.getMinutes()).padStart(2, "0");

    return `${year}-${month}-${day} ${hours}:${minutes}`;
};

export type DateDeadlineTone = "danger" | "warning" | "success" | "default";

export const getDateDeadlineTone = (
    value: string | null | undefined,
): DateDeadlineTone => {
    if (!value) {
        return "default";
    }

    const formattedDate = formatDate(value, "");

    if (!formattedDate) {
        return "default";
    }

    const targetDate = new Date(`${formattedDate}T00:00:00`);
    const now = new Date();
    const today = new Date(
        now.getFullYear(),
        now.getMonth(),
        now.getDate(),
    );

    if (Number.isNaN(targetDate.getTime())) {
        return "default";
    }

    const diffDays = Math.ceil(
        (targetDate.getTime() - today.getTime()) / 86_400_000,
    );

    if (diffDays <= 3) {
        return "danger";
    }

    if (diffDays <= 10) {
        return "warning";
    }

    return "success";
};

export const dateDeadlineColor: Record<DateDeadlineTone, string> = {
    danger: "#ff4d4f",
    warning: "#faad14",
    success: "#52c41a",
    default: "rgba(0, 0, 0, 0.45)",
};