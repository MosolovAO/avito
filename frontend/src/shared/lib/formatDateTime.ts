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

export interface DateDeadlinePresentation {
    text: string;
    tone: DateDeadlineTone;
}

const MILLISECONDS_PER_DAY = 86_400_000;

const defaultDateDeadlinePresentation: DateDeadlinePresentation = {
    text: "не указано",
    tone: "default",
};

const getRussianDayWord = (days: number): "день" | "дня" | "дней" => {
    const lastTwoDigits = days % 100;

    if (lastTwoDigits >= 11 && lastTwoDigits <= 14) {
        return "дней";
    }

    const lastDigit = days % 10;

    if (lastDigit === 1) {
        return "день";
    }

    if (lastDigit >= 2 && lastDigit <= 4) {
        return "дня";
    }

    return "дней";
};

const formatDays = (days: number): string =>
    `${days} ${getRussianDayWord(days)}`;

const getCalendarDateUtc = (
    value: string | null | undefined,
): number | null => {
    const formattedDate = formatDate(value, "");

    if (!DATE_ONLY_PATTERN.test(formattedDate)) {
        return null;
    }

    const [year, month, day] = formattedDate.split("-").map(Number);
    const timestamp = Date.UTC(year, month - 1, day);
    const parsedDate = new Date(timestamp);

    const isValidDate =
        parsedDate.getUTCFullYear() === year &&
        parsedDate.getUTCMonth() === month - 1 &&
        parsedDate.getUTCDate() === day;

    return isValidDate ? timestamp : null;
};

export const getDateDeadlinePresentation = (
    value: string | null | undefined,
    currentDate = new Date(),
): DateDeadlinePresentation => {
    const targetDateUtc = getCalendarDateUtc(value);

    if (targetDateUtc === null) {
        return defaultDateDeadlinePresentation;
    }

    const currentDateUtc = Date.UTC(
        currentDate.getFullYear(),
        currentDate.getMonth(),
        currentDate.getDate(),
    );

    const diffDays =
        (targetDateUtc - currentDateUtc) / MILLISECONDS_PER_DAY;

    if (diffDays < 0) {
        const elapsedDays = Math.abs(diffDays);

        return {
            text: `Снято ${formatDays(elapsedDays)} назад`,
            tone: "danger",
        };
    }

    return {
        text: formatDays(diffDays),
        tone: diffDays <= 10 ? "warning" : "success",
    };
};

export const dateDeadlineColor: Record<DateDeadlineTone, string> = {
    danger: "#ff4d4f",
    warning: "#faad14",
    success: "#52c41a",
    default: "rgba(0, 0, 0, 0.45)",
};