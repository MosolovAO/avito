import React from "react";
import {
    PauseCircleOutlined,
    PlayCircleOutlined,
    StopOutlined,
} from "@ant-design/icons";
import {Button, Space} from "antd";
import type {AvitoAdLifecycleAction} from "../../../entities/avito/types";

interface AdLifecycleBulkActionsProps {
    selectedCount: number;
    disabled?: boolean;
    loading?: boolean;
    onAction: (action: AvitoAdLifecycleAction) => void;
    onClearSelection?: () => void;
}

export const AdLifecycleBulkActions: React.FC<AdLifecycleBulkActionsProps> = ({
                                                                                  selectedCount,
                                                                                  disabled = false,
                                                                                  loading = false,
                                                                                  onAction,
                                                                                  onClearSelection,
                                                                              }) => {
    const isDisabled = disabled || selectedCount === 0;

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

            {selectedCount > 0 && onClearSelection && (
                <Button disabled={loading} onClick={onClearSelection}>
                    Сбросить выбор
                </Button>
            )}
        </Space>
    );
};