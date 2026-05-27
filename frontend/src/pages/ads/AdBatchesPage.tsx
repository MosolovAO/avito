import React, {useState} from "react";
import {Alert, Select, Space, Table, Tag, Typography} from "antd";
import type {TablePaginationConfig, TableProps} from "antd";
import type {
    AdBatch,
    AdBatchSource,
    AdBatchStatus,
    AdBatchesQueryParams,
} from "../../entities/avito/types";
import {useAdBatchesQuery} from "../../features/avito";
import {useCurrentWorkspace} from "../../features/workspace/model/useCurrentWorkspace";

const {Title, Text} = Typography;
const pageSize = 50;

const sourceLabel: Record<AdBatchSource, string> = {
    auto: "Автогенерация",
    manual: "Ручной масс-постинг",
    import: "Импорт Авито",
};

const statusColor: Record<AdBatchStatus, string> = {
    draft: "processing",
    completed: "success",
    failed: "error",
};

export const AdBatchesPage: React.FC = () => {
    const {currentWorkspace} = useCurrentWorkspace()

    const [page, setPage] = useState(1);
    const [source, setSource] = useState<AdBatchSource | undefined>();
    const [status, setStatus] = useState<AdBatchStatus | undefined>();

    const queryParams: AdBatchesQueryParams = {
        page,
        page_size: pageSize,
        source,
        status,
    }

    const batchesQuery = useAdBatchesQuery(queryParams);

    const resetPage = () => setPage(1);

    const columns: TableProps<AdBatch>["columns"] = [
        {
            title: "ID",
            dataIndex: "id",
            key: "id",
            width: 90,
        },
        {
            title: "Источник",
            dataIndex: "source",
            key: "source",
            width: 190,
            render: (value: AdBatchSource) => sourceLabel[value],
        },
        {
            title: "Статус",
            dataIndex: "status",
            key: "status",
            width: 140,
            render: (value: AdBatchStatus) => (
                <Tag color={statusColor[value]}>{value}</Tag>
            ),
        },
        {
            title: "Задача",
            key: "task",
            render: (_, batch) => batch.task_name ?? "Без задачи",
        },
        {
            title: "Создано",
            key: "totals",
            width: 190,
            render: (_, batch) => {
                if (batch.source === "import") {
                    return (
                        <Space orientation="vertical" size={0}>
                            <Text>Креативы: не создаются</Text>
                            <Text type="secondary">Публикации: не создаются</Text>
                        </Space>
                    );
                }

                return (
                    <Space orientation="vertical" size={0}>
                        <Text>Креативы: {batch.total_creatives}</Text>
                        <Text type="secondary">
                            Публикации: {batch.total_publications}
                        </Text>
                    </Space>
                );
            },
        },
        {
            title: "Пользователь",
            dataIndex: "created_by_email",
            key: "created_by_email",
            width: 220,
            render: (value: string | null) => value ?? "Система",
        },
        {
            title: "Время",
            key: "time",
            width: 240,
            render: (_, batch) => (
                <Space orientation="vertical" size={0}>
                    <Text type="secondary">Создано: {batch.created_at}</Text>
                    <Text type="secondary">
                        Завершено: {batch.completed_at ?? "не завершено"}
                    </Text>
                </Space>
            ),
        },
        {
            title: "Ошибка",
            dataIndex: "error_message",
            key: "error_message",
            render: (value: string | null) =>
                value ? <Text type="danger">{value}</Text> : null,
        },
    ]

    const handleTableChange = (pagination: TablePaginationConfig) => {
        setPage(pagination.current ?? 1);
    }

    if (!currentWorkspace) {
        return (
            <Alert
                type="warning"
                message="Кабинет не выбран"
                description="Выберите кабинет, чтобы смотреть историю операций."
                showIcon
            />
        );
    }

    return (
        <Space orientation="vertical" size={16} style={{width: "100%"}}>
            <Space orientation="vertical" size={0}>
                <Title level={2} style={{margin: 0}}>
                    Операции
                </Title>
                <Text type="secondary">
                    История операций: автогенерация и ручной масс-постинг создают креативы и публикации,
                    импорт Avito обновляет только список реальных объявлений.
                </Text>
            </Space>

            <Space wrap size="middle">
                <Select
                    allowClear
                    placeholder="Источник"
                    value={source}
                    style={{width: 220}}
                    options={[
                        {value: "auto", label: "Автогенерация"},
                        {value: "manual", label: "Ручной масс-постинг"},
                        {value: "import", label: "Импорт Авито"},
                    ]}
                    onChange={(value) => {
                        setSource(value);
                        resetPage();
                    }}
                />

                <Select
                    allowClear
                    placeholder="Статус"
                    value={status}
                    style={{width: 180}}
                    options={[
                        {value: "draft", label: "draft"},
                        {value: "completed", label: "completed"},
                        {value: "failed", label: "failed"},
                    ]}
                    onChange={(value) => {
                        setStatus(value);
                        resetPage();
                    }}
                />
            </Space>

            <Table
                rowKey="id"
                columns={columns}
                dataSource={batchesQuery.data?.results ?? []}
                loading={batchesQuery.isLoading}
                onChange={handleTableChange}
                pagination={{
                    current: page,
                    pageSize,
                    total: batchesQuery.data?.count ?? 0,
                    showSizeChanger: false,
                }}
            />
        </Space>
    );
}