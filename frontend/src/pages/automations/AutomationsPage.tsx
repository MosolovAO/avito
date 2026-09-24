import type {FC} from "react";
import {useMemo, useState} from "react";
import {
    MoreOutlined,
    PlusOutlined,
} from "@ant-design/icons";
import {
    Alert,
    Button,
    Card,
    Dropdown,
    message,
    Modal,
    Space,
    Spin,
    Table,
    Tag,
    Typography,
} from "antd";
import type {
    MenuProps,
    TableProps,
} from "antd";
import {
    Link,
    useNavigate,
} from "react-router-dom";

import {
    getAutomationApiError,
    useAutomationCatalogQuery,
    useAutomationsQuery,
} from "../../entities/automation";
import type {
    Automation,
    AutomationState,
} from "../../entities/automation";
import {
    useAvitoProjectsQuery,
} from "../../features/avito";
import {
    useArchiveAutomationMutation,
    useCreateAutomationRunMutation,
    useUpdateAutomationMutation,
} from "../../features/automation-execution";
import {
    useCurrentWorkspace,
} from "../../features/workspace/model/useCurrentWorkspace";

const {Text, Title} = Typography;

const PAGE_SIZE = 20;

const stateLabels: Record<AutomationState, string> = {
    draft: "Черновик",
    enabled: "Включена",
    disabled: "Выключена",
    archived: "В архиве",
};

const dateFormatter = new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "Europe/Moscow",
});

interface AutomationsContentProps {
    workspaceId: number;
}

const getErrorMessage = (
    error: unknown,
    fallback: string,
): string => (
    getAutomationApiError(error)?.message ?? fallback
);

const AutomationsContent: FC<AutomationsContentProps> = ({
                                                             workspaceId,
                                                         }) => {
    const navigate = useNavigate();
    const [page, setPage] = useState(1);

    const automationsQuery = useAutomationsQuery(
        workspaceId,
        page,
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

    const accountNames = useMemo(
        () => new Map(
            (accountsQuery.data ?? []).map(
                (account) => [account.id, account.name],
            ),
        ),
        [accountsQuery.data],
    );

    const actionLabels = useMemo(() => {
        const labels = new Map<string, string>();

        for (const module of catalogQuery.data?.modules ?? []) {
            for (const action of module.actions) {
                labels.set(
                    `${module.module_type}:${action.code}`,
                    action.label,
                );
            }
        }

        return labels;
    }, [catalogQuery.data]);

    if (
        automationsQuery.isLoading ||
        catalogQuery.isLoading ||
        accountsQuery.isLoading
    ) {
        return <Spin size="large"/>;
    }

    if (
        automationsQuery.isError ||
        automationsQuery.data === undefined
    ) {
        return (
            <Alert
                type="error"
                showIcon
                title="Не удалось загрузить автоматизации"
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

    const runAutomation = async (
        automation: Automation,
    ): Promise<void> => {
        const idempotencyKey = crypto.randomUUID();

        try {
            const createdRun = await runMutation.mutateAsync({
                workspaceId,
                automationId: automation.id,
                idempotencyKey,
            });

            navigate(
                `/automation-runs/${createdRun.run_id}`,
            );
        } catch (error) {
            message.error(
                getErrorMessage(
                    error,
                    "Не удалось запустить автоматизацию.",
                ),
            );
        }
    };

    const toggleAutomation = async (
        automation: Automation,
    ): Promise<void> => {
        const nextState = automation.state === "enabled"
            ? "disabled"
            : "enabled";

        try {
            await updateMutation.mutateAsync({
                workspaceId,
                automationId: automation.id,
                payload: {
                    state: nextState,
                },
            });
        } catch (error) {
            message.error(
                getErrorMessage(
                    error,
                    "Не удалось изменить состояние автоматизации.",
                ),
            );
        }
    };

    const confirmArchive = (
        automation: Automation,
    ): void => {
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
                        automationId: automation.id,
                    });
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

    const handleOperation = (
        key: string,
        automation: Automation,
    ): void => {
        switch (key) {
            case "run":
                void runAutomation(automation);
                break;

            case "toggle":
                void toggleAutomation(automation);
                break;

            case "archive":
                confirmArchive(automation);
                break;
        }
    };

    const getOperationItems = (
        automation: Automation,
    ): MenuProps["items"] => [
        {
            key: "run",
            label: "Запустить",
            disabled: automation.state !== "enabled",
        },
        {
            key: "toggle",
            label: automation.state === "enabled"
                ? "Выключить"
                : "Включить",
        },
        {
            key: "archive",
            label: "Архивировать",
            danger: true,
        },
    ];

    const columns: TableProps<Automation>["columns"] = [
        {
            title: "Название",
            dataIndex: "name",
            key: "name",
            width: 260,
            render: (name: string, automation) => (
                <Link
                    to={
                        `/automations/${automation.id}/settings`
                    }
                >
                    {name}
                </Link>
            ),
        },
        {
            title: "Avito-аккаунт",
            key: "avito_account",
            width: 200,
            render: (_, automation) => (
                accountNames.get(
                    automation.config.avito_account_id,
                ) ?? (
                    `Аккаунт #${
                        automation.config.avito_account_id
                    }`
                )
            ),
        },
        {
            title: "Действие",
            key: "action",
            width: 170,
            render: (_, automation) => (
                actionLabels.get(
                    `${automation.module_type}:${
                        automation.config.action.type
                    }`,
                ) ?? automation.config.action.type
            ),
        },
        {
            title: "Состояние",
            dataIndex: "state",
            key: "state",
            width: 140,
            render: (state: AutomationState) => (
                <Tag>{stateLabels[state] ?? state}</Tag>
            ),
        },
        {
            title: "Версия",
            dataIndex: "version",
            key: "version",
            width: 100,
        },
        {
            title: "Дата изменения",
            dataIndex: "updated_at",
            key: "updated_at",
            width: 180,
            render: (updatedAt: string) => (
                dateFormatter.format(new Date(updatedAt))
            ),
        },
        {
            title: "Операции",
            key: "operations",
            width: 100,
            fixed: "right",
            align: "center",
            render: (_, automation) => (
                <Dropdown
                    trigger={["click"]}
                    menu={{
                        items: getOperationItems(automation),
                        onClick: ({key}) => {
                            handleOperation(key, automation);
                        },
                    }}
                >
                    <Button
                        type="text"
                        icon={<MoreOutlined/>}
                        aria-label={
                            `Операции: ${automation.name}`
                        }
                    />
                </Dropdown>
            ),
        },
    ];

    return (
        <Space
            orientation="vertical"
            size={24}
            style={{width: "100%"}}
        >
            <Space
                align="start"
                style={{
                    width: "100%",
                    justifyContent: "space-between",
                }}
            >
                <div>
                    <Title level={2} style={{margin: 0}}>
                        Автоматизации
                    </Title>
                    <Text type="secondary">
                        Правила обработки объявлений Avito
                    </Text>
                </div>

                <Link to="/automations/new">
                    <Button
                        type="primary"
                        icon={<PlusOutlined/>}
                    >
                        Новая автоматизация
                    </Button>
                </Link>
            </Space>

            <Card styles={{body: {padding: 0}}}>
                <Table<Automation>
                    rowKey="id"
                    columns={columns}
                    dataSource={automationsQuery.data.results}
                    loading={automationsQuery.isFetching}
                    scroll={{x: 1150}}
                    pagination={{
                        current: page,
                        pageSize: PAGE_SIZE,
                        total: automationsQuery.data.count,
                        showSizeChanger: false,
                        onChange: setPage,
                    }}
                />
            </Card>
        </Space>
    );
};

export const AutomationsPage: FC = () => {
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
                description={
                    "У вас нет права управлять автоматизациями."
                }
            />
        );
    }

    return (
        <AutomationsContent
            key={currentWorkspaceId}
            workspaceId={currentWorkspaceId}
        />
    );
};