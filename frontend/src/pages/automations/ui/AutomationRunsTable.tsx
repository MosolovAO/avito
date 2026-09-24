import type {FC} from "react";
import {useState} from "react";
import {Alert, Empty, Table, Typography} from "antd";
import type {ColumnsType} from "antd/es/table";
import {
    Link,
    useNavigate,
} from "react-router-dom";

import {
    useAutomationRunsQuery,
} from "../../../entities/automation";
import type {
    AutomationRunSummary,
} from "../../../entities/automation";
import {
    RunStatus,
} from "../../../features/automation-execution";

const {Text} = Typography;

const PAGE_SIZE = 20;

const dateTimeFormatter = new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "Europe/Moscow",
});

interface AutomationRunsTableProps {
    workspaceId: number;
    automationId: number;
}

const formatDateTime = (
    value: string | null,
): string => {
    if (value === null) {
        return "—";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return "—";
    }

    return dateTimeFormatter.format(date);
};

const formatAuthor = (
    createdBy: number | null,
): string => (
    createdBy === null
        ? "Система"
        : `Пользователь #${createdBy}`
);

const formatResult = (
    run: AutomationRunSummary,
): string => (
    `Проверено: ${run.result.checked} · ` +
    `Подошло: ${run.result.matched} · ` +
    `Ожидает: ${run.result.pending_approval} · ` +
    `Выполнено: ${run.result.completed_actions} · ` +
    `Ошибок: ${run.result.failed_actions}`
);

export const AutomationRunsTable: FC<
    AutomationRunsTableProps
> = ({
         workspaceId,
         automationId,
     }) => {
    const navigate = useNavigate();
    const [page, setPage] = useState(1);

    const runsQuery = useAutomationRunsQuery(
        workspaceId,
        automationId,
        page,
    );

    if (runsQuery.isError) {
        return (
            <Alert
                type="error"
                showIcon
                title="Не удалось загрузить журнал запусков"
            />
        );
    }

    const columns: ColumnsType<AutomationRunSummary> = [
        {
            title: "ID",
            dataIndex: "id",
            key: "id",
            width: 90,
            render: (id: number) => (
                <Link
                    to={`/automation-runs/${id}`}
                    onClick={(event) => {
                        event.stopPropagation();
                    }}
                >
                    #{id}
                </Link>
            ),
        },
        {
            title: "Тип",
            dataIndex: "kind",
            key: "kind",
            width: 130,
            render: (
                kind: AutomationRunSummary["kind"],
            ) => (
                kind === "preview"
                    ? "Preview"
                    : "Выполнение"
            ),
        },
        {
            title: "Версия",
            dataIndex: "automation_version",
            key: "automation_version",
            width: 110,
            render: (version: number) => (
                `Версия ${version}`
            ),
        },
        {
            title: "Статус",
            dataIndex: "status",
            key: "status",
            width: 190,
            render: (
                status: AutomationRunSummary["status"],
            ) => (
                <RunStatus status={status}/>
            ),
        },
        {
            title: "Результат",
            key: "result",
            width: 430,
            render: (_, run) => (
                <Text>{formatResult(run)}</Text>
            ),
        },
        {
            title: "Автор",
            dataIndex: "created_by",
            key: "created_by",
            width: 150,
            render: formatAuthor,
        },
        {
            title: "Создан",
            dataIndex: "created_at",
            key: "created_at",
            width: 180,
            render: formatDateTime,
        },
        {
            title: "Начат",
            dataIndex: "started_at",
            key: "started_at",
            width: 180,
            render: formatDateTime,
        },
        {
            title: "Завершён",
            dataIndex: "finished_at",
            key: "finished_at",
            width: 180,
            render: formatDateTime,
        },
    ];

    return (
        <Table<AutomationRunSummary>
            rowKey="id"
            loading={runsQuery.isLoading}
            columns={columns}
            dataSource={runsQuery.data?.results ?? []}
            scroll={{x: 1640}}
            locale={{
                emptyText: (
                    <Empty
                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                        description="Запусков пока нет"
                    />
                ),
            }}
            pagination={{
                current: page,
                pageSize: PAGE_SIZE,
                total: runsQuery.data?.count ?? 0,
                showSizeChanger: false,
                onChange: setPage,
            }}
            onRow={(run) => ({
                style: {cursor: "pointer"},
                onClick: () => {
                    navigate(`/automation-runs/${run.id}`);
                },
            })}
        />
    );
};