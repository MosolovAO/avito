import type {FC} from "react";
import {Tag} from "antd";

interface RunStatusProps {
    status: string;
}

interface StatusPresentation {
    label: string;
    color: string;
}

const statusPresentations: Record<string, StatusPresentation> = {
    queued: {
        label: "В очереди",
        color: "processing",
    },
    waiting_for_data: {
        label: "Ожидает данные",
        color: "gold",
    },
    evaluating: {
        label: "Выполняется проверка",
        color: "blue",
    },
    waiting_approval: {
        label: "Ожидает подтверждения",
        color: "orange",
    },
    effect_pending: {
        label: "Формируется CSV",
        color: "purple",
    },
    completed: {
        label: "Завершён",
        color: "success",
    },
    partial: {
        label: "Завершён частично",
        color: "warning",
    },
    failed: {
        label: "Ошибка",
        color: "error",
    },
    cancelled: {
        label: "Отменён",
        color: "default",
    },
};

export const RunStatus: FC<RunStatusProps> = ({status}) => {
    const presentation = statusPresentations[status];

    if (presentation === undefined) {
        return (
            <Tag>
                Неизвестный статус ({status})
            </Tag>
        );
    }

    return (
        <Tag color={presentation.color}>
            {presentation.label}
        </Tag>
    );
};