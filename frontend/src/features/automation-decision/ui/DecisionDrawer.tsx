import type {FC, ReactNode} from "react";
import {
    Alert,
    Button,
    Card,
    Descriptions,
    Drawer,
    Space,
    Table,
    Tag,
    Typography,
} from "antd";
import type {TableColumnsType} from "antd";
import {
    AutomationConditionTreeView,
} from "../../../entities/automation";
import type {
    AutomationConditionRoot,
    AutomationDecision,
    AutomationDecisionStatus,
    AvitoListingMetricSnapshot,
} from "../../../entities/automation";

const {Text, Title} = Typography;

interface DecisionDrawerProps {
    open: boolean;
    decision: AutomationDecision | null;
    conditionSnapshot: AutomationConditionRoot | null;
    onClose: () => void;
    onApprove: (
        decision: AutomationDecision,
    ) => Promise<void>;
    onReject: (
        decision: AutomationDecision,
    ) => Promise<void>;
    submitting: boolean;
}

interface StatusView {
    label: string;
    color: string;
}

const statusViews: Record<
    AutomationDecisionStatus,
    StatusView
> = {
    pending_approval: {
        label: "Ожидает подтверждения",
        color: "gold",
    },
    applying: {
        label: "Применяется",
        color: "processing",
    },
    effect_pending: {
        label: "Формируется CSV",
        color: "processing",
    },
    completed: {
        label: "Выполнено",
        color: "success",
    },
    rejected: {
        label: "Отклонено",
        color: "default",
    },
    expired: {
        label: "Истекло",
        color: "default",
    },
    stale: {
        label: "Устарело",
        color: "warning",
    },
    superseded: {
        label: "Заменено",
        color: "default",
    },
    failed: {
        label: "Ошибка",
        color: "error",
    },
};

const dateTimeFormatter = new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "Europe/Moscow",
});

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

const formatSnapshotDate = (value: string): string => {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);

    if (match === null) {
        return value;
    }

    return `${match[3]}.${match[2]}.${match[1]}`;
};

const formatMetricPeriod = (
    metric: AvitoListingMetricSnapshot,
): string => (
    `${formatSnapshotDate(metric.date_from)} — ` +
    formatSnapshotDate(metric.date_to)
);

const formatUser = (userId: number | null): string => (
    userId === null ? "—" : `Пользователь #${userId}`
);

const metricColumns: TableColumnsType<
    AvitoListingMetricSnapshot
> = [
    {
        title: "Метрика",
        dataIndex: "metric",
        key: "metric",
        render: (value: string) => <Text code>{value}</Text>,
    },
    {
        title: "Агрегация",
        dataIndex: "aggregation",
        key: "aggregation",
        render: (value: string) => <Text code>{value}</Text>,
    },
    {
        title: "Окно",
        dataIndex: "window_days",
        key: "window_days",
        render: (value: number) => `${value} дней`,
    },
    {
        title: "Период",
        key: "period",
        render: (_, metric) => formatMetricPeriod(metric),
    },
    {
        title: "Значение",
        dataIndex: "value",
        key: "value",
    },
];


const buildProcessingItems = (
    decision: AutomationDecision,
) => [
    {
        key: "approved-by",
        label: "Подтвердил",
        children: formatUser(decision.approved_by),
    },
    {
        key: "approved-at",
        label: "Подтверждено",
        children: formatDateTime(decision.approved_at),
    },
    {
        key: "rejected-by",
        label: "Отклонил",
        children: formatUser(decision.rejected_by),
    },
    {
        key: "rejected-at",
        label: "Отклонено",
        children: formatDateTime(decision.rejected_at),
    },
    {
        key: "action-applied-at",
        label: "Действие применено",
        children: formatDateTime(
            decision.action_applied_at,
        ),
    },
    {
        key: "completed-at",
        label: "Завершено",
        children: formatDateTime(decision.completed_at),
    },
    {
        key: "terminal-at",
        label: "Терминальный статус",
        children: formatDateTime(decision.terminal_at),
    },
    {
        key: "export-revision",
        label: "Ревизия CSV",
        children:
            decision.required_export_revision ?? "—",
    },
    {
        key: "effect-attempts",
        label: "Попытки применения эффекта",
        children: decision.effect_attempts,
    },
    {
        key: "next-effect-retry",
        label: "Следующая попытка",
        children: formatDateTime(
            decision.next_effect_retry_at,
        ),
    },
];

export const DecisionDrawer: FC<DecisionDrawerProps> = ({
                                                            open,
                                                            decision,
                                                            conditionSnapshot,
                                                            onClose,
                                                            onApprove,
                                                            onReject,
                                                            submitting,
                                                        }) => {
    const footer: ReactNode = (
        decision?.status === "pending_approval"
            ? (
                <Space>
                    <Button
                        danger
                        disabled={submitting}
                        onClick={() => {
                            void onReject(decision);
                        }}
                    >
                        Отклонить
                    </Button>

                    <Button
                        type="primary"
                        loading={submitting}
                        disabled={submitting}
                        onClick={() => {
                            void onApprove(decision);
                        }}
                    >
                        Подтвердить действие
                    </Button>
                </Space>
            )
            : null
    );

    const statusView = decision === null
        ? null
        : statusViews[decision.status];

    const actionConfigEntries = decision === null
        ? []
        : Object.keys(decision.action.config);

    return (
        <Drawer
            open={open}
            size="large"
            title={
                decision === null
                    ? "Решение"
                    : `Решение #${decision.id}`
            }
            footer={footer}
            onClose={onClose}
            destroyOnHidden
        >
            {decision === null
                ? null
                : (
                    <Space
                        orientation="vertical"
                        size={20}
                        style={{width: "100%"}}
                    >
                        {decision.error === null
                            ? null
                            : (
                                <Alert
                                    type="error"
                                    showIcon
                                    title="Ошибка выполнения"
                                    description={(
                                        <Space
                                            orientation="vertical"
                                            size={4}
                                        >
                                            <Text code>
                                                {decision.error.code}
                                            </Text>
                                            <Text>
                                                {decision.error.message}
                                            </Text>
                                        </Space>
                                    )}
                                />
                            )}

                        <Descriptions
                            title="Объявление"
                            bordered
                            column={1}
                            items={[
                                {
                                    key: "title",
                                    label: "Название",
                                    children:
                                        decision.listing.title ?? "—",
                                },
                                {
                                    key: "avito-id",
                                    label: "Avito ID",
                                    children:
                                        decision.listing.avito_id ?? "—",
                                },
                                {
                                    key: "listing-id",
                                    label: "ID в сервисе",
                                    children: decision.listing_id,
                                },
                                {
                                    key: "status",
                                    label: "Статус решения",
                                    children: (
                                        <Tag color={statusView?.color}>
                                            {statusView?.label}
                                        </Tag>
                                    ),
                                },
                                {
                                    key: "active-since",
                                    label: "Активно с",
                                    children: formatDateTime(
                                        decision.active_since,
                                    ),
                                },
                                {
                                    key: "expires-at",
                                    label: "Подтвердить до",
                                    children: formatDateTime(
                                        decision.expires_at,
                                    ),
                                },
                            ]}
                        />

                        <div>
                            <Title level={5}>Метрики</Title>
                            <Table
                                rowKey={(metric) => (
                                    `${metric.metric}:` +
                                    `${metric.aggregation}:` +
                                    `${metric.window_days}`
                                )}
                                columns={metricColumns}
                                dataSource={decision.metrics}
                                pagination={false}
                                size="small"
                                scroll={{x: 650}}
                            />
                        </div>

                        {conditionSnapshot === null
                            ? null
                            : (
                                <div>
                                    <Title level={5}>Условия</Title>
                                    <AutomationConditionTreeView
                                        tree={conditionSnapshot}
                                    />
                                </div>
                            )}

                        <Card title="Действие" size="small">
                            <Space
                                orientation="vertical"
                                size={8}
                            >
                                <Text code>
                                    {decision.action.type}
                                </Text>

                                {actionConfigEntries.length === 0
                                    ? null
                                    : (
                                        <Text code>
                                            {JSON.stringify(
                                                decision.action.config,
                                            )}
                                        </Text>
                                    )}
                            </Space>
                        </Card>

                        <Descriptions
                            title="Обработка"
                            bordered
                            column={1}
                            items={buildProcessingItems(decision)}
                        />
                    </Space>
                )}
        </Drawer>
    );
};
