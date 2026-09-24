import type {
    FC,
    ReactNode,
} from "react";
import {useState} from "react";
import {
    Alert,
    Button,
    Card,
    Col,
    Descriptions,
    Empty,
    message,
    Modal,
    notification,
    Row,
    Space,
    Spin,
    Statistic,
    Table,
    Tabs,
    Typography,
} from "antd";
import type {ColumnsType} from "antd/es/table";
import {
    Link,
    useNavigate,
    useParams,
} from "react-router-dom";
import {useQueryClient} from "@tanstack/react-query";
import {
    AutomationRunsTable,
} from "./ui/AutomationRunsTable";
import {
    AutomationConditionTreeView,
    automationKeys,
    AutomationStateTag,
    getAutomationApiError,
    useAutomationCatalogQuery,
    useAutomationQuery,
    useAutomationRunQuery,
    useAutomationRunsQuery,
} from "../../entities/automation";
import type {
    AutomationModuleCatalog,
    AutomationRunDetail,
    AvitoListingExampleSnapshot,
} from "../../entities/automation";
import {
    useAvitoProjectsQuery,
} from "../../features/avito";
import {
    RunStatus,
    useArchiveAutomationMutation,
    useCreateAutomationPreviewMutation,
    useCreateAutomationRunMutation,
    useUpdateAutomationMutation,
} from "../../features/automation-execution";
import {
    useCurrentWorkspace,
} from "../../features/workspace/model/useCurrentWorkspace";

const {Text, Title} = Typography;

interface AutomationPreviewContentProps {
    workspaceId: number;
    automationId: number;
    module: AutomationModuleCatalog | undefined;
}

interface AutomationPreviewRunContentProps {
    workspaceId: number;
    runId: number;
    module: AutomationModuleCatalog | undefined;
}


interface AutomationPreviewSnapshotProps {
    run: AutomationRunDetail;
    module: AutomationModuleCatalog | undefined;
}

const snapshotDatePattern = /^\d{4}-\d{2}-\d{2}$/;

const activeSinceFormatter = new Intl.DateTimeFormat(
    "ru-RU",
    {
        dateStyle: "short",
        timeStyle: "short",
        timeZone: "Europe/Moscow",
    },
);

const previewKpis = [
    {
        key: "checked",
        label: "Проверено",
    },
    {
        key: "ineligible",
        label: "Не подходит",
    },
    {
        key: "insufficient_coverage",
        label: "Недостаточно статистики",
    },
    {
        key: "not_matched",
        label: "Условие не выполнено",
    },
    {
        key: "matched",
        label: "Условие выполнено",
    },
    {
        key: "deferred_by_run_limit",
        label: "Отложено лимитом",
    },
] as const;

const formatSnapshotDate = (value: string): string => {
    if (!snapshotDatePattern.test(value)) {
        return value;
    }

    const [year, month, day] = value.split("-");

    return `${day}.${month}.${year}`;
};

const formatActiveSince = (value: string): string => {
    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return value;
    }

    return activeSinceFormatter.format(date);
};

const formatDays = (days: number): string => {
    const lastTwoDigits = days % 100;
    const lastDigit = days % 10;

    if (lastTwoDigits >= 11 && lastTwoDigits <= 14) {
        return `${days} дней`;
    }

    if (lastDigit === 1) {
        return `${days} день`;
    }

    if (lastDigit >= 2 && lastDigit <= 4) {
        return `${days} дня`;
    }

    return `${days} дней`;
};

const buildPreviewColumns = (
    module: AutomationModuleCatalog | undefined,
): ColumnsType<AvitoListingExampleSnapshot> => [
    {
        title: "ID",
        dataIndex: "listing_id",
        width: 90,
    },
    {
        title: "Avito ID",
        dataIndex: "avito_id",
        width: 150,
    },
    {
        title: "Название",
        dataIndex: "title",
        width: 240,
        render: (title: string | null) => (
            title ?? "Без названия"
        ),
    },
    {
        title: "Активно с",
        dataIndex: "active_since",
        width: 180,
        render: (value: string) => formatActiveSince(value),
    },
    {
        title: "Метрики",
        key: "metrics",
        width: 400,
        render: (
            _value: unknown,
            example: AvitoListingExampleSnapshot,
        ) => (
            <Space
                orientation="vertical"
                size={0}
            >
                {example.metrics.map((metric, index) => {
                    const metricLabel = module?.metrics.find(
                        (item) => item.code === metric.metric,
                    )?.label ?? metric.metric;

                    return (
                        <Text
                            key={
                                `${metric.metric}:` +
                                `${metric.window_days}:` +
                                `${metric.date_from}:` +
                                `${index}`
                            }
                        >
                            {
                                `${metricLabel}: ${metric.value} · ` +
                                `${formatDays(metric.window_days)} · ` +
                                `${formatSnapshotDate(metric.date_from)}` +
                                `—${formatSnapshotDate(metric.date_to)}`
                            }
                        </Text>
                    );
                })}
            </Space>
        ),
    },
];

const AutomationPreviewSnapshot: FC<
    AutomationPreviewSnapshotProps
> = ({
         run,
         module,
     }) => {
    const result = run.result;
    const examples = result.examples_snapshot.slice(0, 20);

    return (
        <Space
            orientation="vertical"
            size={20}
            style={{width: "100%"}}
        >
            <Text type="secondary">
                Статистика по дате{" "}
                {formatSnapshotDate(result.as_of_date)}.
                Результат сохранён в запуске #{run.id}.
            </Text>

            <Row gutter={[16, 16]}>
                {previewKpis.map((item) => (
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

            <div>
                <Title level={4}>Подходящие объявления</Title>

                <Table<AvitoListingExampleSnapshot>
                    rowKey="listing_id"
                    columns={buildPreviewColumns(module)}
                    dataSource={examples}
                    pagination={false}
                    locale={{
                        emptyText: "Нет подходящих объявлений",
                    }}
                    scroll={{x: 1060}}
                />
            </div>
        </Space>
    );
};

const AutomationPreviewRunContent: FC<
    AutomationPreviewRunContentProps
> = ({
         workspaceId,
         runId,
         module,
     }) => {
    const runQuery = useAutomationRunQuery(
        workspaceId,
        runId,
    );

    if (runQuery.isLoading) {
        return <Spin size="large"/>;
    }

    if (runQuery.isError || runQuery.data === undefined) {
        return (
            <Alert
                type="error"
                showIcon
                title="Не удалось загрузить preview"
                description={
                    "Обновите страницу или повторите попытку позже."
                }
            />
        );
    }

    const run = runQuery.data;

    if (
        run.status === "queued" ||
        run.status === "evaluating"
    ) {
        return (
            <Space
                orientation="vertical"
                size={12}
                style={{width: "100%"}}
            >
                <RunStatus status={run.status}/>

                <Space>
                    <Spin size="small"/>
                    <Text>Preview выполняется</Text>
                </Space>
            </Space>
        );
    }

    if (run.status === "waiting_for_data") {
        return (
            <Space
                orientation="vertical"
                size={12}
                style={{width: "100%"}}
            >
                <RunStatus status={run.status}/>

                <Alert
                    type="info"
                    showIcon
                    title="Ожидаем накопления статистики"
                    description={
                        "Запуск продолжится автоматически, когда данные " +
                        "за выбранные периоды будут готовы."
                    }
                />
            </Space>
        );
    }

    if (
        run.status === "failed" ||
        run.status === "cancelled"
    ) {
        return (
            <Space
                orientation="vertical"
                size={12}
                style={{width: "100%"}}
            >
                <RunStatus status={run.status}/>

                <Alert
                    type="error"
                    showIcon
                    title="Preview не завершён"
                    description={
                        run.error?.message ??
                        "Не удалось рассчитать результат preview."
                    }
                />
            </Space>
        );
    }

    return (
        <Space
            orientation="vertical"
            size={12}
            style={{width: "100%"}}
        >
            <RunStatus status={run.status}/>

            <AutomationPreviewSnapshot
                run={run}
                module={module}
            />
        </Space>
    );
};

const AutomationPreviewContent: FC<
    AutomationPreviewContentProps
> = ({
         workspaceId,
         automationId,
         module,
     }) => {
    const [selectedRunId, setSelectedRunId] =
        useState<number | null>(null);

    const runsQuery = useAutomationRunsQuery(
        workspaceId,
        automationId,
        1,
    );

    const previewMutation =
        useCreateAutomationPreviewMutation();

    const startPreview = async (): Promise<void> => {
        const idempotencyKey = crypto.randomUUID();

        try {
            const createdRun =
                await previewMutation.mutateAsync({
                    workspaceId,
                    automationId,
                    idempotencyKey,
                });

            setSelectedRunId(createdRun.run_id);
        } catch (error) {
            const apiError = getAutomationApiError(error);

            if (apiError?.openRunId !== null &&
                apiError?.openRunId !== undefined) {
                setSelectedRunId(apiError.openRunId);
                return;
            }

            if (apiError?.code === "resource_busy") {
                notification.warning({
                    message: "Preview уже выполняется",
                    description: apiError.message,
                });

                void runsQuery.refetch();
                return;
            }

            message.error(
                apiError?.message ??
                "Не удалось запустить preview.",
            );
        }
    };

    if (runsQuery.isLoading) {
        return <Spin size="large"/>;
    }

    if (runsQuery.isError || runsQuery.data === undefined) {
        return (
            <Alert
                type="error"
                showIcon
                title="Не удалось загрузить историю preview"
            />
        );
    }

    const latestPreviewRunId = runsQuery.data.results.find(
        (run) => run.kind === "preview",
    )?.id ?? null;

    const previewRunId =
        selectedRunId ?? latestPreviewRunId;

    return (
        <Space
            orientation="vertical"
            size={20}
            style={{width: "100%"}}
        >
            <div>
                <Button
                    type="primary"
                    loading={previewMutation.isPending}
                    onClick={() => {
                        void startPreview();
                    }}
                >
                    Запустить preview
                </Button>
            </div>

            {previewRunId === null ? (
                <Empty description="Нет доступного preview"/>
            ) : (
                <AutomationPreviewRunContent
                    key={previewRunId}
                    workspaceId={workspaceId}
                    runId={previewRunId}
                    module={module}
                />
            )}
        </Space>
    );
};

interface AutomationDetailContentProps {
    workspaceId: number;
    automationId: number;
    activeTab: string;
}

const getErrorMessage = (
    error: unknown,
    fallback: string,
): string => (
    getAutomationApiError(error)?.message ?? fallback
);

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


const AutomationDetailContent: FC<
    AutomationDetailContentProps
> = ({
         workspaceId,
         automationId,
         activeTab,
     }) => {
    const navigate = useNavigate();
    const queryClient = useQueryClient();

    const automationQuery = useAutomationQuery(
        workspaceId,
        automationId,
    );
    const catalogQuery =
        useAutomationCatalogQuery(workspaceId);
    const accountsQuery = useAvitoProjectsQuery();

    const updateMutation =
        useUpdateAutomationMutation();
    const runMutation =
        useCreateAutomationRunMutation();
    const archiveMutation =
        useArchiveAutomationMutation();

    if (
        automationQuery.isLoading ||
        catalogQuery.isLoading ||
        accountsQuery.isLoading
    ) {
        return <Spin size="large"/>;
    }

    if (
        automationQuery.isError ||
        automationQuery.data === undefined
    ) {
        return (
            <Alert
                type="error"
                showIcon
                title="Автоматизация не найдена"
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

    if (
        accountsQuery.isError ||
        accountsQuery.data === undefined
    ) {
        return (
            <Alert
                type="error"
                showIcon
                title="Не удалось загрузить Avito-аккаунты"
            />
        );
    }

    const automation = automationQuery.data;

    const module = catalogQuery.data.modules.find(
        (item) => item.module_type === automation.module_type,
    );

    const accountName = accountsQuery.data.find(
        (account) => (
            account.id === automation.config.avito_account_id
        ),
    )?.name ?? (
        `Аккаунт #${automation.config.avito_account_id}`
    );

    const actionLabel = module?.actions.find(
        (action) => (
            action.code === automation.config.action.type
        ),
    )?.label ?? automation.config.action.type;

    const runAutomation = async (): Promise<void> => {
        const idempotencyKey = crypto.randomUUID();

        try {
            const createdRun = await runMutation.mutateAsync({
                workspaceId,
                automationId,
                idempotencyKey,
            });

            navigate(
                `/automation-runs/${createdRun.run_id}`,
            );
        } catch (error) {
            const apiError = getAutomationApiError(error);

            if (apiError?.openRunId !== null && apiError?.openRunId !== undefined) {
                navigate(
                    `/automation-runs/${apiError.openRunId}`,
                );
                return;
            }

            if (apiError?.code === "resource_busy") {
                notification.warning({
                    message: "Автоматизация уже выполняется",
                    description: apiError.message,
                });

                await queryClient.invalidateQueries({
                    queryKey: automationKeys.detail(
                        workspaceId,
                        automationId,
                    ),
                });
                return;
            }

            message.error(
                apiError?.message ??
                "Не удалось запустить автоматизацию.",
            );
        }
    };

    const toggleAutomation = async (): Promise<void> => {
        const nextState = automation.state === "enabled"
            ? "disabled"
            : "enabled";

        try {
            await updateMutation.mutateAsync({
                workspaceId,
                automationId,
                payload: {
                    state: nextState,
                },
            });
        } catch (error) {
            const apiError = getAutomationApiError(error);

            if (apiError?.code === "preview_required") {
                message.error(apiError.message);
                navigate(
                    `/automations/${automationId}/preview`,
                );
                return;
            }

            message.error(
                apiError?.message ??
                "Не удалось изменить состояние автоматизации.",
            );
        }
    };

    const confirmArchive = (): void => {
        Modal.confirm({
            title: "Архивировать автоматизацию?",
            content: (
                <>
                    Автоматизация «{automation.name}» будет
                    удалена из активного списка.
                </>
            ),
            okText: "Архивировать",
            okType: "danger",
            cancelText: "Отмена",
            onOk: async () => {
                try {
                    await archiveMutation.mutateAsync({
                        workspaceId,
                        automationId,
                    });

                    navigate("/automations");
                } catch (error) {
                    message.error(
                        getErrorMessage(
                            error,
                            "Не удалось архивировать автоматизацию.",
                        ),
                    );

                    throw error;
                }
            },
        });
    };

    const settingsContent: ReactNode = (
        <Space
            orientation="vertical"
            size={20}
            style={{width: "100%"}}
        >
            <Descriptions
                bordered
                column={1}
                items={[
                    {
                        key: "module",
                        label: "Сущность",
                        children:
                            module?.label ??
                            automation.module_type,
                    },
                    {
                        key: "account",
                        label: "Avito-аккаунт",
                        children: accountName,
                    },
                    {
                        key: "action",
                        label: "Действие",
                        children: actionLabel,
                    },
                    {
                        key: "max-actions",
                        label: "Лимит действий",
                        children: (
                            `${automation.config.max_actions_per_run} объявлений`
                        ),
                    },
                    {
                        key: "approval-ttl",
                        label: "Срок подтверждения",
                        children: formatHours(
                            automation.config.approval_ttl_minutes / 60,
                        ),
                    },
                    {
                        key: "execution-mode",
                        label: "Режим выполнения",
                        children: automation.execution_mode === "manual"
                            ? "Ручной"
                            : automation.execution_mode,
                    },
                    {
                        key: "version",
                        label: "Версия",
                        children: `Версия ${automation.version}`,
                    },
                ]}
            />

            <div>
                <Title level={4}>Условия</Title>
                <AutomationConditionTreeView
                    tree={automation.config.condition_tree}
                    module={module}
                />
            </div>
        </Space>
    );

    return (
        <Space
            orientation="vertical"
            size={24}
            style={{width: "100%"}}
        >
            <Space
                align="start"
                wrap
                style={{
                    width: "100%",
                    justifyContent: "space-between",
                }}
            >
                <div>
                    <Space size={12} align="center">
                        <Title level={2} style={{margin: 0}}>
                            {automation.name}
                        </Title>
                        <AutomationStateTag
                            state={automation.state}
                        />
                    </Space>
                    <Text type="secondary">
                        Версия {automation.version}
                    </Text>
                </div>

                <Space wrap>
                    <Link
                        to={
                            `/automations/${automationId}/edit`
                        }
                    >
                        <Button>Редактировать</Button>
                    </Link>

                    <Button
                        type="primary"
                        disabled={automation.state !== "enabled"}
                        loading={runMutation.isPending}
                        onClick={() => {
                            void runAutomation();
                        }}
                    >
                        Запустить
                    </Button>

                    <Button
                        loading={updateMutation.isPending}
                        onClick={() => {
                            void toggleAutomation();
                        }}
                    >
                        {automation.state === "enabled"
                            ? "Выключить"
                            : "Включить"}
                    </Button>

                    <Button
                        danger
                        loading={archiveMutation.isPending}
                        onClick={confirmArchive}
                    >
                        Архивировать
                    </Button>
                </Space>
            </Space>

            <Card>
                <Tabs
                    activeKey={activeTab}
                    onChange={(tab) => {
                        navigate(
                            `/automations/${automationId}/${tab}`,
                        );
                    }}
                    items={[
                        {
                            key: "settings",
                            label: "Настройка",
                            children: settingsContent,
                        },
                        {
                            key: "preview",
                            label: "Preview",
                            children: (
                                <AutomationPreviewContent
                                    workspaceId={workspaceId}
                                    automationId={automationId}
                                    module={module}
                                />
                            ),
                        },
                        {
                            key: "runs",
                            label: "Запуски",
                            children: (
                                <AutomationRunsTable
                                    workspaceId={workspaceId}
                                    automationId={automationId}
                                />
                            ),
                        },
                    ]}
                />
            </Card>
        </Space>
    );
};

export const AutomationDetailPage: FC = () => {
    const {
        automationId: automationIdParam,
        tab: tabParam,
    } = useParams<{
        automationId?: string;
        tab?: string;
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

    const automationId = Number(automationIdParam);

    if (
        !Number.isInteger(automationId) ||
        automationId <= 0
    ) {
        return (
            <Alert
                type="error"
                showIcon
                title="Некорректный ID автоматизации"
            />
        );
    }

    const activeTab = (
        tabParam === "preview" ||
        tabParam === "runs"
    )
        ? tabParam
        : "settings";

    return (
        <AutomationDetailContent
            key={`${currentWorkspaceId}:${automationId}`}
            workspaceId={currentWorkspaceId}
            automationId={automationId}
            activeTab={activeTab}
        />
    );
};