import React, {useState} from "react";

import {
    CalendarOutlined,
    EditOutlined,
    FilterOutlined,
    LinkOutlined,
    ReloadOutlined,
    RollbackOutlined,
    SearchOutlined,
} from "@ant-design/icons";

import {useNavigate, useSearchParams} from "react-router-dom";

import {
    Alert,
    Button,
    Drawer,
    Input,
    Select,
    Space,
    Table,
    Tag,
    Tooltip,
    Typography,
} from "antd";
import type {TablePaginationConfig, TableProps} from "antd";
import type {
    AdPublication,
    AdPublicationSource,
    AdPublicationStatus,
    AdPublicationsQueryParams,
    AvitoAdLifecycleAction
} from "../../entities/avito/types";
import {
    useAdPublicationsQuery,
    useAvitoProjectsQuery,
    useLinkAvitoPublicationsMutation,
    useExtendAdPublicationMutation,
    useInheritAdPublicationCreativeDateEndMutation,
    AdLifecycleBulkActions,
    useBulkUpdateAvitoAdsLifecycleMutation,
} from "../../features/avito";

import {useCurrentWorkspace} from "../../features/workspace/model/useCurrentWorkspace";
import {
    dateDeadlineColor,
    formatDate,
    formatDateTime,
    getDateDeadlineTone,
} from "../../shared/lib/formatDateTime";

const {Title, Text} = Typography;

const pageSize = 50;


const publicationStatusColor: Record<AdPublicationStatus, string> = {
    draft: "default",
    active: "success",
    paused: "warning",
    archived: "default",
    error: "error"
};

const publicationSourceLabel: Record<AdPublicationSource, string> = {
    auto: "Автогенерация",
    manual: "Ручной масс-постинг",
};

export const AdPublicationsPage: React.FC = () => {
    const {currentWorkspace, canManageAvitoAccounts} = useCurrentWorkspace();
    const [page, setPage] = useState(1);
    const [avitoAccountId, setAvitoAccountId] = useState<number | undefined>();
    const [status, setStatus] = useState<AdPublicationStatus | undefined>();
    const [source, setSource] = useState<AdPublicationSource | undefined>();
    const [search, setSearch] = useState("")
    const [selectedPublicationIds, setSelectedPublicationIds] = useState<number[]>([]);
    const [filtersDrawerOpen, setFiltersDrawerOpen] = useState(false);
    const navigate = useNavigate();
    const [searchParams, setSearchParams] = useSearchParams();
    const bulkLifecycleMutation = useBulkUpdateAvitoAdsLifecycleMutation();
    const batchParam = searchParams.get("batch");
    const batchId = batchParam ? Number(batchParam) : undefined;


    const queryParams: AdPublicationsQueryParams = {
        page,
        page_size: pageSize,
        avito_account: avitoAccountId,
        status,
        source,
        batch: batchId,
        search: search.trim() || undefined,
    };

    const publicationsQuery = useAdPublicationsQuery(queryParams)
    const projectsQuery = useAvitoProjectsQuery()
    const linkPublicationsMutation = useLinkAvitoPublicationsMutation();
    const extendPublicationMutation = useExtendAdPublicationMutation();
    const inheritCreativeDateEndMutation = useInheritAdPublicationCreativeDateEndMutation();

    const resetPage = () => {
        setPage(1);
        setSelectedPublicationIds([]);
    };

    const activeFiltersCount = [
        avitoAccountId,
        status,
        source,
    ].filter(Boolean).length;

    const resetFilters = () => {
        setAvitoAccountId(undefined);
        setStatus(undefined);
        setSource(undefined);
        resetPage();
    };

    const clearBatchFilter = () => {
        const nextParams = new URLSearchParams(searchParams);
        nextParams.delete("batch");
        setSearchParams(nextParams);
        setPage(1);
    };

    const handleBulkLifecycle = (action: AvitoAdLifecycleAction) => {
        if (!avitoAccountId || selectedPublicationIds.length === 0) {
            return;
        }

        bulkLifecycleMutation.mutate(
            {
                avitoAccountId,
                items: selectedPublicationIds.map((id) => ({
                    entity_type: "ad_publication",
                    id,
                })),
                action,
            },
            {
                onSuccess: () => {
                    setSelectedPublicationIds([]);
                },
            },
        );
    };

    const selectedProject = (projectsQuery.data ?? []).find(
        (project) => project.id === avitoAccountId
    )

    const dateEndSourceLabel: Record<AdPublication["date_end_source"], string> = {
        publication: "Индивидуально",
        creative: "Креатив",
        default: "30 дней",
    };

    const rowSelection: TableProps<AdPublication>["rowSelection"] = {
        selectedRowKeys: selectedPublicationIds,
        onChange: (selectedRowKeys) => {
            setSelectedPublicationIds(
                selectedRowKeys
                    .map((key) => Number(key))
                    .filter((key) => Number.isFinite(key)),
            );
        },
        getCheckboxProps: (publication) => ({
            disabled:
                !canManageAvitoAccounts ||
                !avitoAccountId ||
                publication.avito_account !== avitoAccountId,
        }),
    };

    const columns: TableProps<AdPublication>["columns"] = [
        {
            title: "Объявление",
            key: "creative",
            width: 320,
            render: (_, publication) => (
                <Space orientation="vertical" size={0}>
                    <Text strong>{publication.creative_title}</Text>
                    <Text type="secondary">{publication.address || "Адрес не указан"}</Text>
                </Space>
            ),
        },
        {
            title: "row_id",
            dataIndex: "row_id",
            key: "row_id",
            width: 210,
            render: (value: string | null) =>
                value ? (
                    <Text copyable>
                        {value}
                    </Text>
                ) : (
                    <Tag>Нет row_id</Tag>
                ),
        },
        {
            title: "Проект",
            dataIndex: "avito_account_name",
            key: "avito_account_name",
            width: 200,
        },
        {
            title: "Окончание",
            key: "date_end",
            width: 150,
            render: (_, publication) => {
                const deadlineTone = getDateDeadlineTone(publication.effective_date_end);

                return (
                    <Tooltip title={dateEndSourceLabel[publication.date_end_source]}>
                        <Text style={{color: dateDeadlineColor[deadlineTone]}}>
                            {formatDate(publication.effective_date_end)}
                        </Text>
                    </Tooltip>
                );
            },
        },
        {
            title: "Статус",
            key: "status",
            width: 150,
            render: (_, publication) => (
                <Space orientation="vertical" size={4}>
                    <Tag color={publicationStatusColor[publication.status]}>
                        {publication.status}
                    </Tag>
                    <Tag>{publicationSourceLabel[publication.source]}</Tag>
                </Space>
            ),
        },
        {
            title: "Avito",
            key: "avito",
            width: 110,
            render: (_, publication) => {
                if (!publication.avito_id) {
                    return <Tag>Не связана</Tag>;
                }

                return (
                    <Space orientation="vertical" size={0}>
                        <Text copyable>{publication.avito_id}</Text>
                        {publication.avito_listing_url && (
                            <Button
                                type="link"
                                size="small"
                                icon={<LinkOutlined/>}
                                href={publication.avito_listing_url}
                                target="_blank"
                                rel="noreferrer"
                                style={{padding: 0}}
                            >
                                Открыть на Avito
                            </Button>
                        )}
                    </Space>
                );
            },
        },
        {
            title: "Экспорт",
            key: "export",
            width: 200,
            render: (_, publication) => (
                <Space orientation="vertical" size={0}>
                    <Text type="secondary" style={{fontSize: 10}}>
                        Последний экспорт: {formatDateTime(publication.last_exported_at)}
                    </Text>
                    <Text type="secondary" style={{fontSize: 11, fontWeight: "bold"}}>
                        Создано: {formatDateTime(publication.created_at)}
                    </Text>
                </Space>
            ),
        },

        {
            title: "Действия",
            key: "actions",
            width: 100,
            fixed: "right",
            onHeaderCell: () => ({
                style: {
                    backgroundColor: "#fafafa",
                },
            }),
            onCell: () => ({
                style: {
                    backgroundColor: "#fafafa",
                },
            }),
            render: (_, publication) => (
                <Space>
                    <Tooltip title="Продлить публикацию на 30 дней">
                        <Button
                            icon={<CalendarOutlined/>}
                            disabled={!canManageAvitoAccounts}
                            loading={
                                extendPublicationMutation.isPending &&
                                extendPublicationMutation.variables === publication.id
                            }
                            onClick={() => extendPublicationMutation.mutate(publication.id)}
                        />
                    </Tooltip>

                    {publication.date_end_source === "publication" && (
                        <Tooltip title="Вернуть срок креатива">
                            <Button
                                icon={<RollbackOutlined/>}
                                disabled={!canManageAvitoAccounts}
                                loading={
                                    inheritCreativeDateEndMutation.isPending &&
                                    inheritCreativeDateEndMutation.variables === publication.id
                                }
                                onClick={() => inheritCreativeDateEndMutation.mutate(publication.id)}
                            />
                        </Tooltip>
                    )}


                    <Tooltip title="Изменить публикацию">
                        <Button
                            icon={<EditOutlined/>}
                            disabled={!canManageAvitoAccounts}
                            onClick={() => navigate(`/ads/publications/${publication.id}/edit`)}
                        />
                    </Tooltip>
                </Space>
            ),
        },
    ];

    const handleTableChange = (pagination: TablePaginationConfig) => {
        setPage(pagination.current ?? 1)
    }

    const handleLinkCurrentProject = () => {
        if (!avitoAccountId) {
            return
        }

        linkPublicationsMutation.mutate({
            avitoAccountId
        })
    }

    if (!currentWorkspace) {
        return (
            <Alert
                type="warning"
                message="Кабинет не выбран"
                description="Выберите кабинет, чтобы смотреть публикации."
                showIcon
            />
        );
    }

    return (
        <Space orientation="vertical" size={16} style={{width: "100%"}}>
            <Space orientation="vertical" size={0}>
                <Title level={2} style={{margin: 0}}>
                    Публикации
                </Title>
                <Text type="secondary">
                    Строки автозагрузки, созданные из креативов по адресам. Связь с Avito ID появляется после выгрузки и
                    сопоставления.
                </Text>
            </Space>

            <div
                style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    flexWrap: "wrap",
                    width: "100%",
                }}
            >
                <Input
                    allowClear
                    prefix={<SearchOutlined/>}
                    placeholder="Поиск по row_id, адресу, названию или Avito ID"
                    value={search}
                    style={{width: 360}}
                    onChange={(event) => {
                        setSearch(event.target.value);
                        resetPage();
                    }}
                />

                <Select
                    allowClear
                    placeholder="Проект"
                    value={avitoAccountId}
                    style={{width: 200}}
                    loading={projectsQuery.isLoading}
                    options={(projectsQuery.data ?? []).map((project) => ({
                        value: project.id,
                        label: project.name,
                    }))}
                    onChange={(value) => {
                        setAvitoAccountId(value);
                        resetPage();
                    }}
                />

                <Tooltip
                    title={
                        avitoAccountId
                            ? "Связать публикации выбранного проекта с Avito ID"
                            : "Сначала выберите проект"
                    }
                >
                    <Button
                        icon={<ReloadOutlined/>}
                        disabled={
                            !canManageAvitoAccounts ||
                            !avitoAccountId ||
                            !selectedProject?.external_account_id
                        }
                        loading={linkPublicationsMutation.isPending}
                        onClick={handleLinkCurrentProject}
                    >
                        Связать с Avito ID
                    </Button>
                </Tooltip>

                <AdLifecycleBulkActions
                    selectedCount={selectedPublicationIds.length}
                    disabled={!canManageAvitoAccounts || !avitoAccountId}
                    loading={bulkLifecycleMutation.isPending}
                    onAction={handleBulkLifecycle}
                    onClearSelection={() => setSelectedPublicationIds([])}
                />

                <Button
                    icon={<FilterOutlined/>}
                    type={activeFiltersCount > 0 ? "primary" : "default"}
                    onClick={() => setFiltersDrawerOpen(true)}
                    style={{marginLeft: "auto"}}
                >
                    {activeFiltersCount > 0 ? `Фильтры (${activeFiltersCount})` : "Фильтры"}
                </Button>
            </div>

            {batchId && (
                <Alert
                    type="info"
                    showIcon
                    message={`Показаны публикации операции #${batchId}`}
                    action={
                        <Button size="small" onClick={clearBatchFilter}>
                            Показать все
                        </Button>
                    }
                />
            )}

            <Table<AdPublication>
                rowKey="id"
                columns={columns}
                dataSource={publicationsQuery.data?.results ?? []}
                loading={publicationsQuery.isLoading}
                onChange={handleTableChange}
                rowSelection={rowSelection}
                tableLayout="fixed"
                scroll={{x: 1900}}
                rowHoverable={false}
                pagination={{
                    current: page,
                    pageSize,
                    total: publicationsQuery.data?.count ?? 0,
                    showSizeChanger: false,
                }}
            />

            <Drawer
                title="Фильтры"
                open={filtersDrawerOpen}
                width={360}
                onClose={() => setFiltersDrawerOpen(false)}
                extra={
                    <Button onClick={resetFilters} disabled={activeFiltersCount === 0}>
                        Сбросить
                    </Button>
                }
            >
                <Space direction="vertical" size={16} style={{width: "100%"}}>
                    <Select
                        allowClear
                        placeholder="Статус"
                        value={status}
                        style={{width: "100%"}}
                        options={[
                            {value: "draft", label: "draft"},
                            {value: "active", label: "active"},
                            {value: "paused", label: "paused"},
                            {value: "archived", label: "archived"},
                            {value: "error", label: "error"},
                        ]}
                        onChange={(value) => {
                            setStatus(value);
                            resetPage();
                        }}
                    />

                    <Select
                        allowClear
                        placeholder="Источник"
                        value={source}
                        style={{width: "100%"}}
                        options={[
                            {value: "auto", label: "Автогенерация"},
                            {value: "manual", label: "Ручной масс-постинг"},
                        ]}
                        onChange={(value) => {
                            setSource(value);
                            resetPage();
                        }}
                    />
                </Space>
            </Drawer>
        </Space>
    );


}
