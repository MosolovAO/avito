import type {FC} from "react";
import {Tag} from "antd";

interface AutomationStateTagProps {
    state: string;
}

interface StatePresentation {
    label: string;
    color: string;
}

const statePresentations: Record<string, StatePresentation> = {
    draft: {
        label: "Черновик",
        color: "default",
    },
    enabled: {
        label: "Включена",
        color: "success",
    },
    disabled: {
        label: "Выключена",
        color: "warning",
    },
    archived: {
        label: "В архиве",
        color: "default",
    },
};

export const AutomationStateTag: FC<
    AutomationStateTagProps
> = ({state}) => {
    const presentation = statePresentations[state];

    if (presentation === undefined) {
        return (
            <Tag>
                Неизвестное состояние ({state})
            </Tag>
        );
    }

    return (
        <Tag color={presentation.color}>
            {presentation.label}
        </Tag>
    );
};