import type {
    FC,
    ReactNode,
} from "react";
import {
    Alert,
    message,
    Spin,
} from "antd";
import {
    useNavigate,
    useParams,
} from "react-router-dom";

import {
    getAutomationApiError,
    useAutomationCatalogQuery,
    useAutomationQuery,
    useAutomationRunsQuery,
} from "../../entities/automation";
import {
    AutomationWizard,
} from "../../features/automation-builder";
import type {
    AutomationWizardSubmission,
} from "../../features/automation-builder";
import {
    useAvitoProjectsQuery,
} from "../../features/avito";
import {
    useCreateAutomationMutation,
    useCreateAutomationPreviewMutation,
    useUpdateAutomationMutation,
} from "../../features/automation-execution";
import {
    useCurrentWorkspace,
} from "../../features/workspace/model/useCurrentWorkspace";

import styles from "./AutomationEditorPage.module.scss";

interface EditorDataProps {
    workspaceId: number;
    automationId: number | null;
}

interface CreateEditorProps {
    workspaceId: number;
    catalog: ReturnType<
        typeof useAutomationCatalogQuery
    >["data"];
    accounts: ReturnType<
        typeof useAvitoProjectsQuery
    >["data"];
}

interface EditEditorProps extends CreateEditorProps {
    automationId: number;
}

const AutomationEditorLayout: FC<{
    children: ReactNode;
}> = ({children}) => (
    <div className={styles.surface}>
        <div className={styles.page}>
            {children}
        </div>
    </div>
);

const getErrorMessage = (
    error: unknown,
    fallback: string,
): string => (
    getAutomationApiError(error)?.message ?? fallback
);

const CreateAutomationEditor: FC<
    CreateEditorProps
> = ({
         workspaceId,
         catalog,
         accounts,
     }) => {
    const navigate = useNavigate();

    const createMutation =
        useCreateAutomationMutation();
    const previewMutation =
        useCreateAutomationPreviewMutation();

    if (catalog === undefined || accounts === undefined) {
        return null;
    }

    const handleSubmit = async (
        payload: AutomationWizardSubmission,
    ): Promise<void> => {
        let createdAutomation;

        try {
            createdAutomation =
                await createMutation.mutateAsync({
                    workspaceId,
                    payload,
                });
        } catch (error) {
            message.error(
                getErrorMessage(
                    error,
                    "Не удалось сохранить автоматизацию.",
                ),
            );
            return;
        }

        const idempotencyKey = crypto.randomUUID();

        try {
            await previewMutation.mutateAsync({
                workspaceId,
                automationId: createdAutomation.id,
                idempotencyKey,
            });
        } catch (error) {
            message.error(
                getAutomationApiError(error)?.message ??
                (
                    "Автоматизация сохранена, но preview " +
                    "не запущен. Повторите запуск на " +
                    "вкладке Preview."
                ),
            );
        }

        navigate(
            `/automations/${createdAutomation.id}/preview`,
        );
    };

    return (
        <AutomationEditorLayout>
            <AutomationWizard
                mode="create"
                catalog={catalog}
                accounts={accounts.map((account) => ({
                    id: account.id,
                    name: account.name,
                }))}
                accountLocked={false}
                submitting={
                    createMutation.isPending ||
                    previewMutation.isPending
                }
                onCancel={() => {
                    navigate("/automations");
                }}
                onManageAccounts={() => {
                    navigate("/projects");
                }}
                onSubmit={handleSubmit}
            />
        </AutomationEditorLayout>
    );
};

const EditAutomationEditor: FC<
    EditEditorProps
> = ({
         workspaceId,
         automationId,
         catalog,
         accounts,
     }) => {
    const navigate = useNavigate();

    const automationQuery =
        useAutomationQuery(
            workspaceId,
            automationId,
        );
    const runsQuery =
        useAutomationRunsQuery(
            workspaceId,
            automationId,
            1,
        );

    const updateMutation =
        useUpdateAutomationMutation();
    const previewMutation =
        useCreateAutomationPreviewMutation();

    if (
        catalog === undefined ||
        accounts === undefined
    ) {
        return null;
    }

    if (
        automationQuery.isLoading ||
        runsQuery.isLoading
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
                    "Проверьте, что автоматизация существует " +
                    "и принадлежит текущему кабинету."
                }
            />
        );
    }

    if (
        runsQuery.isError ||
        runsQuery.data === undefined
    ) {
        return (
            <Alert
                type="error"
                showIcon
                title="Не удалось проверить историю запусков"
                description={
                    "Редактирование временно недоступно, " +
                    "поскольку нельзя определить возможность " +
                    "смены Avito-аккаунта."
                }
            />
        );
    }

    const handleSubmit = async (
        payload: AutomationWizardSubmission,
    ): Promise<void> => {
        let updatedAutomation;

        try {
            updatedAutomation =
                await updateMutation.mutateAsync({
                    workspaceId,
                    automationId,
                    payload: {
                        name: payload.name,
                        config: payload.config,
                    },
                });
        } catch (error) {
            message.error(
                getErrorMessage(
                    error,
                    "Не удалось сохранить автоматизацию.",
                ),
            );
            return;
        }

        const idempotencyKey = crypto.randomUUID();

        try {
            await previewMutation.mutateAsync({
                workspaceId,
                automationId: updatedAutomation.id,
                idempotencyKey,
            });
        } catch (error) {
            message.error(
                getAutomationApiError(error)?.message ??
                (
                    "Автоматизация сохранена, но preview " +
                    "не запущен. Повторите запуск на " +
                    "вкладке Preview."
                ),
            );
        }

        navigate(
            `/automations/${updatedAutomation.id}/preview`,
        );
    };

    return (
        <AutomationEditorLayout>
            <AutomationWizard
                mode="edit"
                catalog={catalog}
                accounts={accounts.map((account) => ({
                    id: account.id,
                    name: account.name,
                }))}
                initialAutomation={automationQuery.data}
                accountLocked={runsQuery.data.count > 0}
                submitting={
                    updateMutation.isPending ||
                    previewMutation.isPending
                }
                onCancel={() => {
                    navigate("/automations");
                }}
                onManageAccounts={() => {
                    navigate("/projects");
                }}
                onSubmit={handleSubmit}
            />
        </AutomationEditorLayout>
    );
};

const EditorData: FC<EditorDataProps> = ({
                                             workspaceId,
                                             automationId,
                                         }) => {
    const catalogQuery =
        useAutomationCatalogQuery(workspaceId);
    const accountsQuery =
        useAvitoProjectsQuery();

    if (
        catalogQuery.isLoading ||
        accountsQuery.isLoading
    ) {
        return <Spin size="large"/>;
    }

    if (
        catalogQuery.isError ||
        catalogQuery.data === undefined
    ) {
        return (
            <Alert
                type="error"
                showIcon
                title="Не удалось загрузить конструктор"
                description={
                    "Повторите попытку после загрузки " +
                    "каталога автоматизаций."
                }
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

    if (automationId === null) {
        return (
            <CreateAutomationEditor
                workspaceId={workspaceId}
                catalog={catalogQuery.data}
                accounts={accountsQuery.data}
            />
        );
    }

    return (
        <EditAutomationEditor
            workspaceId={workspaceId}
            automationId={automationId}
            catalog={catalogQuery.data}
            accounts={accountsQuery.data}
        />
    );
};

export const AutomationEditorPage: FC = () => {
    const {automationId: automationIdParam} = useParams<{
        automationId?: string;
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
                type="warning"
                showIcon
                title="Недостаточно прав"
                description={
                    "Управление автоматизациями доступно " +
                    "только владельцу и администраторам."
                }
            />
        );
    }

    if (automationIdParam === undefined) {
        return (
            <EditorData
                workspaceId={currentWorkspaceId}
                automationId={null}
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

    return (
        <EditorData
            workspaceId={currentWorkspaceId}
            automationId={automationId}
        />
    );
};
