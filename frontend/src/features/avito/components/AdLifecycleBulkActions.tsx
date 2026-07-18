import React from "react";
import {
    CalendarOutlined,
    PauseCircleOutlined,
    PlayCircleOutlined,
    StopOutlined,
} from "@ant-design/icons";
import {Button, Popconfirm, Space, Tooltip} from "antd";
import type {AvitoAdLifecycleAction} from "../../../entities/avito/types";

interface AdLifecycleBulkActionsProps {
    selectedCount: number;
    extendableCount?: number;
    disabled?: boolean;
    loading?: boolean;
    onAction: (action: AvitoAdLifecycleAction) => void;
    onClearSelection?: () => void;
}

export const AdLifecycleBulkActions: React.FC<AdLifecycleBulkActionsProps> = ({
                                                                                  selectedCount,
                                                                                  extendableCount,
                                                                                  disabled = false,
                                                                                  loading = false,
                                                                                  onAction,
                                                                                  onClearSelection,
                                                                              }) => {
    const isDisabled = disabled || selectedCount === 0;
    const isExtendDisabled =
        disabled ||
        loading ||
        extendableCount === undefined ||
        extendableCount === 0;

    return (
        <Space wrap>

            <Button
                icon={<PlayCircleOutlined/>}
                disabled={isDisabled}
                loading={loading}
                onClick={() => onAction("publish")}
            >

            </Button>

            <Button
                icon={<PauseCircleOutlined/>}
                disabled={isDisabled}
                loading={loading}
                onClick={() => onAction("pause")}
            >

            </Button>

            <Button
                danger
                icon={<StopOutlined/>}
                disabled={isDisabled}
                loading={loading}
                onClick={() => onAction("delete")}
            >

            </Button>

            {extendableCount !== undefined && (
                <Popconfirm
                    title="Продлить выбранные объявления?"
                    description={`Срок будет продлён на 30 дней для ${extendableCount} объявлений.`}
                    okText="Продлить"
                    cancelText="Отмена"
                    disabled={isExtendDisabled}
                    onConfirm={() => onAction("extend")}
                >
                    <Tooltip
                        title="Продлить объявление на 30 дней"
                    >

                        <Button
                            type="primary"
                            icon={<CalendarOutlined/>}
                            disabled={isExtendDisabled}
                            loading={loading}
                        >


                        </Button>
                    </Tooltip>
                </Popconfirm>
            )}

            {selectedCount > 0 && onClearSelection && (
                <Button disabled={loading} onClick={onClearSelection}>
                    Сбросить выбор
                </Button>
            )}
        </Space>
    );
};