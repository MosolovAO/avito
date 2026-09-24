import {useState} from "react";
import type {FC} from "react";
import {
    Button,
    message,
    Modal,
    notification,
    Table,
    Tag,
    Alert,
    Card,
    Col,
    Descriptions,
    Row,
    Space,
    Spin,
    Statistic,
    Typography,
} from "antd";
import type {TableColumnsType} from "antd";
import {
    Link,
    useParams,
} from "react-router-dom";

import {
    AutomationConditionTreeView,
    getAutomationApiError,
    useAutomationCatalogQuery,
    useAutomationDecisionsQuery,
    useAutomationRunQuery,
} from "../../entities/automation";
import type {
    AutomationDecision,
    AutomationDecisionStatus,
    AutomationModuleCatalog,
    AutomationRunDetail,
    DecisionCommandResponse,
} from "../../entities/automation";
import {
    DecisionDrawer,
    useApproveAutomationDecisionMutation,
    useRejectAutomationDecisionMutation,
} from "../../features/automation-decision";
import {
    RunStatus,
} from "../../features/automation-execution";
import {
    useCurrentWorkspace,
} from "../../features/workspace/model/useCurrentWorkspace";

const {Text, Title} = Typography;

const dateTimeFormatter = new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "Europe/Moscow",
});

const runKpis = [
    {key: "checked", label: "Проверено"},
    {key: "ineligible", label: "Не подходит"},
    {
        key: "insufficient_coverage",
        label: "Недостаточно статистики",
    },
    {key: "not_matched", label: "Условие не выполнено"},
    {key: "matched", label: "Условие выполнено"},
    {
        key: "deferred_by_run_limit",
        label: "Отложено лимитом",
    },
    {
        key: "pending_approval",
        label: "Ожидает подтверждения",
    },
    {
        key: "completed_actions",
        label: "Выполнено действий",
    },
    {key: "failed_actions", label: "Ошибок действий"},
] as const;

interface RunContentProps {
    workspaceId: number;
    runId: number;
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

const formatSnapshotDate = (value: string): string => {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);

    if (match === null) {
        return value;
    }

    return `${match[3]}.${match[2]}.${match[1]}`;
};

const formatHours = (hours: number): string => {
    const lastTwoDigits = hours % 100;
    const lastDigit = hours % 10;

    if (lastTwoDigits >= 11 && lastTwoDigits <= 14) {
        return `${hours} часов`;
    }

    if (lastDigit === 1) {
        return `${hours} час`;
    }

    if (lastDigit >= 2 && lastDigit <= 4) {
        return `${hours} часа`;
    }

    return `${hours} часов`;
};

const formatApprovalTtl = (minutes: number): string => (
    minutes % 60 === 0
        ? formatHours(minutes / 60)
        : `${minutes} минут`
);


const RunSnapshot: FC<{
    run: AutomationRunDetail;
    module: AutomationModuleCatalog | undefined;
}> = ({
          run,
          module,
      }) => {
    const result = run.result;

    const actionLabel = module?.actions.find(
        (action) => (
            action.code === result.action_snapshot.type
        ),
    )?.label ?? result.action_snapshot.type;

    const hasWaitingDetails = (
        run.retry_count > 0 ||
        run.data_wait_attempt_count > 0 ||
        run.wait_started_at !== null ||
        run.next_attempt_at !== null
    );

    const actionConfigEntries = Object.keys(
        result.action_snapshot.config,
    );

    return (
        <Space
            orientation="vertical"
            size={24}
            style={{width: "100%"}}
        >
            {run.error !== null && (
                <Alert
                    type={
                        run.status === "waiting_for_data"
                            ? "info"
                            : "error"
                    }
                    showIcon
                    title={
                        run.status === "waiting_for_data"
                            ? "Ожидаем накопления статистики"
                            : "Ошибка запуска"
                    }
                    description={(
                        <Space orientation="vertical" size={4}>
                            <Text code>{run.error.code}</Text>
                            <Text>{run.error.message}</Text>
                        </Space>
                    )}
                />
            )}

            {run.status === "effect_pending" && (
                <Alert
                    type="info"
                    showIcon
                    title="О CSV-эффекте"
                    description={
                        "Действие включено в сформированный CSV " +
                        "нужной ревизии. Это ещё не является " +
                        "подтверждением, что изменение уже принято " +
                        "и применено Avito."
                    }
                />
            )}

            <Descriptions
                title="Запуск"
                bordered
                column={2}
                items={[
                    {
                        key: "automation",
                        label: "Автоматизация",
                        children: run.automation_name,
                    },
                    {
                        key: "version",
                        label: "Версия",
                        children:
                            `Версия ${run.automation_version}`,
                    },
                    {
                        key: "kind",
                        label: "Тип",
                        children: run.kind === "preview"
                            ? "Preview"
                            : "Выполнение",
                    },
                    {
                        key: "trigger",
                        label: "Способ запуска",
                        children: run.trigger === "manual"
                            ? "Ручной запуск"
                            : run.trigger,
                    },
                    {
                        key: "execution-mode",
                        label: "Режим выполнения",
                        children: run.execution_mode === "manual"
                            ? "Ручной"
                            : run.execution_mode,
                    },
                    {
                        key: "author",
                        label: "Автор",
                        children: run.created_by === null
                            ? "Система"
                            : `Пользователь #${run.created_by}`,
                    },
                    {
                        key: "created",
                        label: "Создан",
                        children: formatDateTime(run.created_at),
                    },
                    {
                        key: "started",
                        label: "Начат",
                        children: formatDateTime(run.started_at),
                    },
                    {
                        key: "finished",
                        label: "Завершён",
                        children: formatDateTime(run.finished_at),
                    },
                    {
                        key: "updated",
                        label: "Обновлён",
                        children: formatDateTime(run.updated_at),
                    },
                ]}
            />

            <Descriptions
                title="Зафиксированные параметры"
                bordered
                column={2}
                items={[
                    {
                        key: "account",
                        label: "Avito-аккаунт",
                        children:
                            `Аккаунт #${result.avito_account_id}`,
                    },
                    {
                        key: "as-of-date",
                        label: "Дата статистики",
                        children:
                            formatSnapshotDate(result.as_of_date),
                    },
                    {
                        key: "max-actions",
                        label: "Лимит действий",
                        children:
                            `${result.max_actions_per_run_snapshot} ` +
                            "объявлений",
                    },
                    {
                        key: "approval-ttl",
                        label: "Срок подтверждения",
                        children: formatApprovalTtl(
                            result.approval_ttl_minutes_snapshot,
                        ),
                    },
                ]}
            />

            {hasWaitingDetails && (
                <Descriptions
                    title="Повторные попытки и ожидание"
                    bordered
                    column={2}
                    items={[
                        {
                            key: "retry-count",
                            label: "Попытки выполнения",
                            children: run.retry_count,
                        },
                        {
                            key: "data-wait-attempt-count",
                            label: "Попытки ожидания данных",
                            children:
                            run.data_wait_attempt_count,
                        },
                        {
                            key: "wait-started-at",
                            label: "Ожидание началось",
                            children: formatDateTime(
                                run.wait_started_at,
                            ),
                        },
                        {
                            key: "next-attempt-at",
                            label: "Следующая попытка",
                            children: formatDateTime(
                                run.next_attempt_at,
                            ),
                        },
                    ]}
                />
            )}

            <div>
                <Title level={4}>Результаты</Title>

                <Row gutter={[16, 16]}>
                    {runKpis.map((item) => (
                        <Col
                            key={item.key}
                            xs={24}
                            sm={12}
                            lg={8}
                        >
                            <Card size="small">
                                <Statistic
                                    title={item.label}
                                    value={result[item.key]}
                                />
                            </Card>
                        </Col>
                    ))}
                </Row>
            </div>

            <div>
                <Title level={4}>Условия</Title>
                <AutomationConditionTreeView
                    tree={result.condition_snapshot}
                    module={module}
                />
            </div>

            <Card title="Действие" size="small">
                <Space orientation="vertical" size={8}>
                    <Text strong>{actionLabel}</Text>

                    {actionConfigEntries.length > 0 && (
                        <Text code>
                            {JSON.stringify(
                                result.action_snapshot.config,
                            )}
                        </Text>
                    )}
                </Space>
            </Card>
        </Space>
    );
};

const decisionStatusLabels: Record<
    AutomationDecisionStatus,
    string
> = {
    pending_approval: "Ожидает подтверждения",
    applying: "Применяется",
    effect_pending: "Формируется CSV",
    completed: "Выполнено",
    rejected: "Отклонено",
    expired: "Истекло",
    stale: "Устарело",
    superseded: "Заменено",
    failed: "Ошибка",
};

interface RunDecisionsProps {
    workspaceId: number;
    runId: number;
    conditionSnapshot: AutomationRunDetail["result"]["condition_snapshot"];
    module: AutomationModuleCatalog | undefined;
    onRefreshRun: () => Promise<unknown>;
}

const RunDecisions: FC<RunDecisionsProps> = ({
                                                 workspaceId,
                                                 runId,
                                                 conditionSnapshot,
                                                 module,
                                                 onRefreshRun,
                                             }) => {
    const [page, setPage] = useState(1);
    const [
        selectedDecision,
        setSelectedDecision,
    ] = useState<AutomationDecision | null>(null);

    const decisionsQuery = useAutomationDecisionsQuery(
        workspaceId,
        runId,
        page,
    );

    const approveMutation =
        useApproveAutomationDecisionMutation();

    const rejectMutation =
        useRejectAutomationDecisionMutation();

    const currentDecision = selectedDecision === null
        ? null
        : decisionsQuery.data?.results.find(
        (decision) => (
            decision.id === selectedDecision.id
        ),
    ) ?? selectedDecision;

    const updateSelectedFromResponse = (
        response: DecisionCommandResponse,
    ): void => {
        setSelectedDecision((current) => {
            if (
                current === null ||
                current.id !== response.decision_id
            ) {
                return current;
            }

            return {
                ...current,
                status: response.status,
                required_export_revision:
                response.required_export_revision,
            };
        });
    };

    const handleCommandError = async (
        error: unknown,
        fallbackMessage: string,
    ): Promise<void> => {
        const apiError = getAutomationApiError(error);

        if (apiError?.code === "resource_busy") {
            notification.warning({
                message: "Avito-аккаунт уже обрабатывается",
                description: apiError.message,
            });

            await Promise.all([
                onRefreshRun(),
                decisionsQuery.refetch(),
            ]);
            return;
        }

        message.error(
            apiError?.message ?? fallbackMessage,
        );
    };

    const executeApprove = async (
        decision: AutomationDecision,
    ): Promise<void> => {
        try {
            const response =
                await approveMutation.mutateAsync({
                    workspaceId,
                    runId,
                    decisionId: decision.id,
                });

            updateSelectedFromResponse(response);
        } catch (error) {
            await handleCommandError(
                error,
                "Не удалось подтвердить решение.",
            );
        }
    };

    const executeReject = async (
        decision: AutomationDecision,
    ): Promise<void> => {
        try {
            const response =
                await rejectMutation.mutateAsync({
                    workspaceId,
                    runId,
                    decisionId: decision.id,
                });

            updateSelectedFromResponse(response);
        } catch (error) {
            await handleCommandError(
                error,
                "Не удалось отклонить решение.",
            );
        }
    };

    const approveDecision = (
        decision: AutomationDecision,
    ): Promise<void> => {
        if (decision.action.type !== "archive") {
            return executeApprove(decision);
        }

        Modal.confirm({
            title: "Архивировать объявление?",
            content: (
                <>
                    Объявление будет окончательно снято.
                    Автоматизация не сможет восстановить его
                    автоматически.
                </>
            ),
            okText: "Архивировать",
            okType: "danger",
            cancelText: "Отмена",
            onOk: () => executeApprove(decision),
        });

        return Promise.resolve();
    };

    const rejectDecision = (
        decision: AutomationDecision,
    ): Promise<void> => {
        Modal.confirm({
            title: "Отклонить решение?",
            content:
                "Запланированное действие не будет выполнено.",
            okText: "Отклонить",
            okType: "danger",
            cancelText: "Отмена",
            onOk: () => executeReject(decision),
        });

        return Promise.resolve();
    };

    const columns: TableColumnsType<AutomationDecision> = [
        {
            title: "Объявление",
            key: "listing",
            render: (_, decision) => (
                <Button
                    type="link"
                    style={{padding: 0}}
                    onClick={() => {
                        setSelectedDecision(decision);
                    }}
                >
                    {decision.listing.title ??
                        `Объявление #${decision.listing_id}`}
                </Button>
            ),
        },
        {
            title: "Avito ID",
            key: "avito-id",
            render: (_, decision) => (
                decision.listing.avito_id ?? "—"
            ),
        },
        {
            title: "Действие",
            key: "action",
            render: (_, decision) => (
                module?.actions.find(
                    (action) => (
                        action.code === decision.action.type
                    ),
                )?.label ?? decision.action.type
            ),
        },
        {
            title: "Статус",
            dataIndex: "status",
            key: "status",
            render: (status: AutomationDecisionStatus) => (
                <Tag>
                    {decisionStatusLabels[status]}
                </Tag>
            ),
        },
        {
            title: "Подтвердить до",
            dataIndex: "expires_at",
            key: "expires_at",
            render: (value: string) => formatDateTime(value),
        },
    ];

    const submitting = (
        approveMutation.isPending ||
        rejectMutation.isPending
    );

    return (
        <div>
            <Title level={4}>Решения</Title>

            {decisionsQuery.isLoading
                ? <Spin/>
                : decisionsQuery.isError ||
                decisionsQuery.data === undefined
                    ? (
                        <Alert
                            type="error"
                            showIcon
                            title="Не удалось загрузить решения"
                        />
                    )
                    : (
                        <Table
                            rowKey="id"
                            columns={columns}
                            dataSource={
                                decisionsQuery.data.results
                            }
                            pagination={{
                                current: page,
                                pageSize: 20,
                                total: decisionsQuery.data.count,
                                showSizeChanger: false,
                                hideOnSinglePage: true,
                                onChange: (nextPage) => {
                                    setPage(nextPage);
                                    setSelectedDecision(null);
                                },
                            }}
                            scroll={{x: 800}}
                        />
                    )}

            <DecisionDrawer
                open={currentDecision !== null}
                decision={currentDecision}
                conditionSnapshot={conditionSnapshot}
                submitting={submitting}
                onClose={() => {
                    if (!submitting) {
                        setSelectedDecision(null);
                    }
                }}
                onApprove={approveDecision}
                onReject={rejectDecision}
            />
        </div>
    );
};

const RunContent: FC<RunContentProps> = ({
                                             workspaceId,
                                             runId,
                                         }) => {
    const runQuery = useAutomationRunQuery(
        workspaceId,
        runId,
    );
    const catalogQuery =
        useAutomationCatalogQuery(workspaceId);

    if (runQuery.isLoading || catalogQuery.isLoading) {
        return <Spin size="large"/>;
    }

    if (runQuery.isError || runQuery.data === undefined) {
        return (
            <Alert
                type="error"
                showIcon
                title="Запуск не найден"
                description={
                    "Проверьте адрес или выбранный рабочий кабинет."
                }
            />
        );
    }

    if (
        catalogQuery.isError ||
        catalogQuery.data === undefined
    ) {
        return (
            <Alert
                type="error"
                showIcon
                title="Не удалось загрузить каталог автоматизаций"
            />
        );
    }

    const run = runQuery.data;

    const module = catalogQuery.data.modules.find(
        (item) => item.module_type === run.module_type,
    );

    return (
        <Space
            orientation="vertical"
            size={24}
            style={{width: "100%"}}
        >
            <div>
                <Link to={`/automations/${run.automation_id}/runs`}>
                    К запускам автоматизации
                </Link>

                <Space
                    align="center"
                    size={12}
                    wrap
                    style={{
                        display: "flex",
                        marginTop: 12,
                    }}
                >
                    <Title level={2} style={{margin: 0}}>
                        Запуск #{run.id}
                    </Title>
                    <RunStatus status={run.status}/>
                </Space>
            </div>

            <RunSnapshot
                run={run}
                module={module}
            />

            {run.kind === "execute"
                ? (
                    <RunDecisions
                        workspaceId={workspaceId}
                        runId={runId}
                        conditionSnapshot={
                            run.result.condition_snapshot
                        }
                        module={module}
                        onRefreshRun={() => runQuery.refetch()}
                    />
                )
                : null}
        </Space>
    );
};

export const AutomationRunPage: FC = () => {
    const {runId: runIdParam} = useParams<{
        runId?: string;
    }>();

    const {
        currentWorkspaceId,
        canManageAutomations,
    } = useCurrentWorkspace();

    if (currentWorkspaceId === null) {
        return (
            <Alert
                type="warning"
                showIcon
                title="Рабочий кабинет не выбран"
            />
        );
    }

    if (!canManageAutomations) {
        return (
            <Alert
                type="error"
                showIcon
                title="Доступ запрещён"
            />
        );
    }

    const runId = Number(runIdParam);

    if (!Number.isInteger(runId) || runId <= 0) {
        return (
            <Alert
                type="error"
                showIcon
                title="Некорректный ID запуска"
            />
        );
    }

    return (
        <RunContent
            key={`${currentWorkspaceId}:${runId}`}
            workspaceId={currentWorkspaceId}
            runId={runId}
        />
    );
};
