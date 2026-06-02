import React, {useEffect, useState} from "react";
import {
    ApiOutlined,
    CopyOutlined,
    DeleteOutlined,
    EditOutlined,
    PlusOutlined,
    ReloadOutlined,
} from "@ant-design/icons";
import {
    Alert,
    Button,
    DatePicker,
    Form,
    Input,
    message,
    Modal,
    Popconfirm,
    Space,
    Switch,
    Table,
    Tag,
    Tooltip,
    Typography,
} from "antd";
import type {TableProps} from "antd";
import type {Dayjs} from "dayjs";
import type {AvitoAccount} from "../../entities/avito/types";
import {
    useAvitoProjectsQuery,
    useCreateAvitoProjectMutation,
    useDeleteAvitoProjectMutation,
    useImportAvitoDailyStatsMutation,
    useLinkAvitoPublicationsMutation,
    useUpdateAvitoProjectMutation,
    useVerifyAvitoConnectionMutation,
} from "../../features/avito";

import {useCurrentWorkspace} from "../../features/workspace/model/useCurrentWorkspace";
import {useConnectAvitoAccountMutation} from "../../features/avito/model/useAvitoActions.ts";

const {RangePicker} = DatePicker;
const {Title, Text} = Typography;

interface ProjectFormValues {
    name: string;
    client_id?: string;
    client_secret?: string;
    is_active: boolean;
}

interface StatsFormValues {
    period: [Dayjs, Dayjs]
}

const exportStatusColor: Record<AvitoAccount["export_status"], string> = {
    clean: "success",
    dirty: "warning",
    queued: "processing",
    exporting: "processing",
    error: "error",
};

const exportStatusLabel: Record<AvitoAccount["export_status"], string> = {
    clean: "CSV актуален",
    dirty: "Нужна пересборка",
    queued: "CSV в очереди",
    exporting: "CSV формируется",
    error: "Ошибка CSV",
};


const getConnectionTag = (project: AvitoAccount) => {
    if (project.connection_status === "not_configured") {
        return <Tag color="warning">API ключи не заданы</Tag>;
    }

    if (project.connection_status === "not_connected") {
        return <Tag>API не подключен</Tag>;
    }

    if (project.connection_status === "error") {
        return <Tag color="error">Ошибка API</Tag>;
    }

    return (
        <Tag color="success">
            API подключен: {project.external_account_id}
        </Tag>
    );
};

const getExportStatusTag = (project: AvitoAccount) => (
    <Tag color={exportStatusColor[project.export_status]}>
        {exportStatusLabel[project.export_status]}
    </Tag>
);

export const ProjectsPage: React.FC = () => {
    const {currentWorkspace, canManageAvitoAccounts} = useCurrentWorkspace();
    const [projectForm] = Form.useForm<ProjectFormValues>()
    const [statsForm] = Form.useForm<StatsFormValues>()

    const [editingProject, setEditingProject] = useState<AvitoAccount | null>(
        null,
    );

    const [isProjectModalOpen, setIsProjectModalOpen] = useState(false)
    const [statsProject, setStatsProject] = useState<AvitoAccount | null>(null)

    const projectsQuery = useAvitoProjectsQuery();
    const createProjectMutation = useCreateAvitoProjectMutation()
    const updateProjectMutation = useUpdateAvitoProjectMutation();
    const deleteProjectMutation = useDeleteAvitoProjectMutation();

    const connectAvitoMutation = useConnectAvitoAccountMutation();
    const linkPublicationsMutation = useLinkAvitoPublicationsMutation();
    const importStatsMutation = useImportAvitoDailyStatsMutation();

    const verifyConnectionMutation = useVerifyAvitoConnectionMutation();

    const isSyncInProgress = (account: AvitoAccount) =>
        account.sync_status === "queued" || account.sync_status === "syncing";

    const handleLinkPublications = (avitoAccountId: number) => {
        linkPublicationsMutation.mutate(
            {avitoAccountId},
            {
                onSuccess: () => {
                    void projectsQuery.refetch();
                },
            },
        );
    };

    const hasActiveSync = (projectsQuery.data ?? []).some(isSyncInProgress);

    useEffect(() => {
        if (!hasActiveSync) {
            return;
        }

        const intervalId = window.setInterval(() => {
            void projectsQuery.refetch();
        }, 3000);

        return () => {
            window.clearInterval(intervalId);
        };
    }, [hasActiveSync, projectsQuery]);

    const formatDateTime = (value: string | null): string => {
        if (!value) {
            return "не было";
        }

        const date = new Date(value);

        if (Number.isNaN(date.getTime())) {
            return value;
        }

        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, "0");
        const day = String(date.getDate()).padStart(2, "0");
        const hours = String(date.getHours()).padStart(2, "0");
        const minutes = String(date.getMinutes()).padStart(2, "0");

        return `${year}-${month}-${day} ${hours}:${minutes}`;
    };

    const getSyncStatusText = (account: AvitoAccount) => {
        if (account.sync_status === "queued") {
            return "Синхронизация поставлена в очередь";
        }

        if (account.sync_status === "syncing") {
            return "Синхронизация отчета автозагрузки выполняется";
        }

        if (account.sync_status === "error") {
            return "Ошибка синхронизации";
        }

        if (account.last_synced_at) {
            return `Последняя синхронизация: ${formatDateTime(account.last_synced_at)}`;
        }

        return "Синхронизация еще не выполнялась";
    };

    const getSyncStatusColor = (status?: string) => {
        if (status === "queued") return "processing";
        if (status === "syncing") return "processing";
        if (status === "error") return "error";

        return "default";
    };
    const openCreateModal = () => {
        setEditingProject(null);
        projectForm.setFieldsValue({
            name: "",
            client_id: "",
            client_secret: "",
            is_active: true,
        });
        setIsProjectModalOpen(true);
    };

    const openEditModal = (project: AvitoAccount) => {
        setEditingProject(project);
        projectForm.setFieldsValue({
            name: project.name,
            client_id: project.client_id,
            client_secret: "",
            is_active: project.is_active,
        });
        setIsProjectModalOpen(true);
    };

    const closeProjectModal = () => {
        setIsProjectModalOpen(false);
        setEditingProject(null);
        projectForm.resetFields();
    }

    const submitProjectForm = async () => {
        const values = await projectForm.validateFields();

        const payload = {
            ...values,
            name: values.name.trim(),
            client_id: values.client_id?.trim(),
            client_secret: values.client_secret?.trim() || undefined,
        };

        if (editingProject) {
            await updateProjectMutation.mutateAsync({
                avitoAccountId: editingProject.id,
                data: payload,
            });
        } else {
            await createProjectMutation.mutateAsync(payload);
        }

        closeProjectModal();
    };

    const openStatsModal = (project: AvitoAccount) => {
        setStatsProject(project);
        statsForm.resetFields()
    }

    const closeStatsModal = () => {
        setStatsProject(null);
        statsForm.resetFields();
    }

    const submitStatsImport = async () => {
        if (!statsProject) {
            return;
        }

        const values = await statsForm.validateFields();
        const [dateFrom, dateTo] = values.period;

        await importStatsMutation.mutateAsync({
            avitoAccountId: statsProject.id,
            payload: {
                date_from: dateFrom.format("YYYY-MM-DD"),
                date_to: dateTo.format("YYYY-MM-DD")
            }
        });

        closeStatsModal()
    }


    const copyFeedUrl = async (project: AvitoAccount) => {
        if (!project.feed_url) {
            message.warning("Ссылка автозагрузки еще не сформирована");
            return;
        }

        await navigator.clipboard.writeText(project.feed_url);
        message.success("Ссылка автозагрузки скопирована");
    };

    const columns: TableProps<AvitoAccount>["columns"] = [
        {
            title: "Проект",
            dataIndex: "name",
            key: "name",
            width: 240,
            render: (_, project) => (
                <Space orientation="vertical" size={0}>
                    <Text strong>{project.name}</Text>

                    {project.external_account_id && (
                        <Text type="secondary" style={{fontSize: 12}}>
                            Avito ID: {project.external_account_id}
                        </Text>
                    )}
                </Space>
            ),
        },
        {
            title: "Avito API",
            key: "avito",
            width: 260,
            render: (_, project) => (
                <Space orientation="vertical" size={4}>
                    {getConnectionTag(project)}

                    {project.connection_error && (
                        <Text type="danger">{project.connection_error}</Text>
                    )}

                    {project.last_verified_at && (
                        <Text type="secondary" style={{fontSize: 10, }}>
                            Проверено: {formatDateTime(project.last_verified_at)}
                        </Text>
                    )}

                </Space>
            ),
        },
        {
            title: "Автозагрузка",
            key: "autoload",
            width: 420,
            render: (_, project) => (
                <Space direction="vertical" size={6} style={{width: "100%"}}>
                    {getExportStatusTag(project)}

                    <Space.Compact style={{width: "100%"}}>
                        <Input
                            readOnly
                            value={project.feed_url ?? ""}
                            placeholder="Ссылка автозагрузки не сформирована"
                        />

                        <Tooltip title="Скопировать ссылку для кабинета Avito">
                            <Button
                                icon={<CopyOutlined/>}
                                disabled={!project.feed_url}
                                onClick={() => copyFeedUrl(project)}
                            />
                        </Tooltip>
                    </Space.Compact>

                    {project.export_error && (
                        <Text type="danger">{project.export_error}</Text>
                    )}
                </Space>
            ),
        },
        {
            title: "Синхронизация",
            key: "sync",
            width: 300,
            render: (_, project) => (
                <Space direction="vertical" size={4}>
                    <Tag color={getSyncStatusColor(project.sync_status)}>
                        {getSyncStatusText(project)}
                    </Tag>

                    {(project.sync_status === "queued" || project.sync_status === "syncing") && (
                        <Text type="secondary" style={{fontSize: 12}}>
                            Можно продолжать работу, результат обновится после завершения задачи.
                        </Text>
                    )}

                    {project.sync_error && (
                        <Text type="danger" style={{fontSize: 12}}>
                            {project.sync_error}
                        </Text>
                    )}

                    {project.last_synced_at && (
                        <Text type="secondary" style={{fontSize: 12}}>
                            Строк отчета: {project.last_sync_total_received ?? 0} · Создано связей:{" "}
                            {project.last_sync_created_listings ?? 0} · Обновлено объявлений:{" "}
                            {project.last_sync_updated_listings ?? 0}
                        </Text>
                    )}
                </Space>
            ),
        },

        {
            title: "Действия",
            key: "actions",
            width: 420,
            render: (_, project) => {
                const hasConnectedAvito = Boolean(project.external_account_id);
                const hasAvitoCredentials = Boolean(
                    project.client_id && project.has_client_secret,
                );

                return (
                    <Space wrap size="small">
                        <Tooltip title="Редактировать проект">
                            <Button
                                icon={<EditOutlined/>}
                                disabled={!canManageAvitoAccounts}
                                onClick={() => openEditModal(project)}
                            />
                        </Tooltip>

                        <Tooltip
                            title={
                                hasAvitoCredentials
                                    ? "Проверить ключи и подключить Avito API"
                                    : "Сначала укажите Client ID и Client Secret"
                            }
                        >
                            <Button
                                icon={<ApiOutlined/>}
                                disabled={!canManageAvitoAccounts || !hasAvitoCredentials}
                                loading={connectAvitoMutation.isPending}
                                onClick={() =>
                                    connectAvitoMutation.mutate({avitoAccountId: project.id})
                                }
                            >
                                Подключить API
                            </Button>
                        </Tooltip>

                        <Tooltip title="Проверить текущее подключение Avito API">
                            <Button
                                disabled={!canManageAvitoAccounts || !project.external_account_id}
                                loading={verifyConnectionMutation.isPending}
                                onClick={() =>
                                    verifyConnectionMutation.mutate({
                                        avitoAccountId: project.id,
                                    })
                                }
                            >
                                Проверить
                            </Button>
                        </Tooltip>

                        <Button
                            onClick={() => handleLinkPublications(project.id)}
                            loading={project.sync_status === "queued" || project.sync_status === "syncing"}
                            disabled={project.sync_status === "queued" || project.sync_status === "syncing"}
                        >
                            Обновить связи с Avito
                        </Button>

                        <Tooltip title="Импортировать статистику">
                            <Button
                                icon={<ReloadOutlined/>}
                                disabled={!canManageAvitoAccounts || !hasConnectedAvito}
                                onClick={() => openStatsModal(project)}
                            />
                        </Tooltip>

                        <Popconfirm
                            title="Удалить проект?"
                            description="Будут удалены данные Avito-аккаунта этого проекта."
                            okText="Удалить"
                            cancelText="Отмена"
                            onConfirm={() => deleteProjectMutation.mutate(project.id)}
                        >
                            <Button
                                danger
                                icon={<DeleteOutlined/>}
                                disabled={!canManageAvitoAccounts}
                                loading={deleteProjectMutation.isPending}
                            />
                        </Popconfirm>
                    </Space>

                );
            },
        },
    ];

    if (!currentWorkspace) {
        return (
            <Alert
                type="warning"
                message="Кабинет не выбран"
                description="Выберите кабинет, чтобы управлять проектом"
                showIcon
            />
        )
    }

    return (
        <Space orientation="vertical" size={16} style={{width: "100%"}}>
            <div style={{display: "flex", justifyContent: "space-between", gap: 16}}>
                <Space orientation="vertical" size={0}>
                    <Title level={2} style={{margin: 0}}>
                        Проекты
                    </Title>
                    <Text type="secondary">
                        Каждый проект соответствует отдельному Avito-аккаунту и отдельной CSV-выгрузке.
                    </Text>
                </Space>

                <Button
                    type="primary"
                    icon={<PlusOutlined/>}
                    disabled={!canManageAvitoAccounts}
                    onClick={openCreateModal}
                >
                    Создать проект
                </Button>
            </div>

            {!canManageAvitoAccounts && (
                <Alert
                    type="info"
                    message="Недостаточно прав для управления проектами"
                    description="Вы можете просматривать проекты, но подключение Avito и изменения доступны только ролям с правом manage_avito_accounts."
                    showIcon
                />
            )}

            <Table
                rowKey="id"
                columns={columns}
                dataSource={projectsQuery.data ?? []}
                loading={projectsQuery.isLoading}
                pagination={{pageSize: 10}}
                scroll={{x: 1700}}
            />

            <Modal
                title={editingProject ? "Редактировать проект" : "Создать проект"}
                open={isProjectModalOpen}
                okText={editingProject ? "Сохранить" : "Создать"}
                cancelText="Отмена"
                confirmLoading={
                    createProjectMutation.isPending || updateProjectMutation.isPending
                }
                onOk={submitProjectForm}
                onCancel={closeProjectModal}
            >
                <Form
                    form={projectForm}
                    layout="vertical"
                    initialValues={{is_active: true}}
                >
                    <Form.Item
                        name="name"
                        label="Название проекта"
                        rules={[
                            {required: true, message: "Введите название проекта"},
                            {max: 255, message: "Максимум 255 символов"},
                        ]}
                    >
                        <Input placeholder="Например: Москва - Недвижимость"/>
                    </Form.Item>

                    <Form.Item
                        name="client_id"
                        label="Client ID Avito"
                        rules={[
                            {required: true, message: "Введите Client ID"},
                            {max: 255, message: "Максимум 255 символов"},
                        ]}
                    >
                        <Input placeholder="Client ID приложения Avito"/>
                    </Form.Item>

                    <Form.Item
                        name="client_secret"
                        label="Client Secret Avito"
                        extra={
                            editingProject?.has_client_secret
                                ? "Секрет уже задан. Оставьте поле пустым, если не хотите менять его."
                                : undefined
                        }
                        rules={[
                            {
                                required: !editingProject?.has_client_secret,
                                message: "Введите Client Secret",
                            },
                        ]}
                    >
                        <Input.Password
                            placeholder={
                                editingProject?.has_client_secret
                                    ? "Оставьте пустым, чтобы не менять"
                                    : "Client Secret приложения Avito"
                            }
                        />
                    </Form.Item>

                    <Form.Item
                        name="is_active"
                        label="Активен"
                        valuePropName="checked"
                    >
                        <Switch/>
                    </Form.Item>
                </Form>
            </Modal>

            <Modal
                title={
                    statsProject
                        ? `Импорт статистики: ${statsProject.name}`
                        : "Импорт статистики"
                }
                open={Boolean(statsProject)}
                okText="Импортировать"
                cancelText="Отмена"
                confirmLoading={importStatsMutation.isPending}
                onOk={submitStatsImport}
                onCancel={closeStatsModal}
            >
                <Form form={statsForm} layout="vertical">
                    <Form.Item
                        name="period"
                        label="Период"
                        rules={[{required: true, message: "Выберите период"}]}
                    >
                        <RangePicker style={{width: "100%"}}/>
                    </Form.Item>
                </Form>
            </Modal>
        </Space>
    );


}
