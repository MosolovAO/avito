// src/pages/ads/AdCreativesPage.tsx
import React, {useState} from "react";
import {CalendarOutlined, DeleteOutlined, EditOutlined, FilterOutlined, SearchOutlined} from "@ant-design/icons";
import {
    Alert,
    Button,
    Drawer,
    Input,
    Select,
    Space,
    Table,
    Tag,
    Modal,
    Typography,
    Tooltip,
} from "antd";
import type {TablePaginationConfig, TableProps} from "antd";
import {useNavigate} from "react-router-dom";
import type {
    AdCreative,
    AdCreativeSource,
    AdCreativesQueryParams,
} from "../../entities/avito/types";

import {
    useAdCreativesQuery,
    useAvitoProjectsQuery,
    useDeleteAdCreativeMutation,
    useExtendAdCreativePublicationsMutation,
} from "../../features/avito";

import {useCurrentWorkspace} from "../../features/workspace/model/useCurrentWorkspace";
import {
    dateDeadlineColor,
    formatDateTime,
    getDateDeadlinePresentation,
} from "../../shared/lib/formatDateTime";

const {Title, Text, Paragraph} = Typography;

const pageSize = 50;

const creativeSourceLabel: Record<AdCreativeSource, string> = {
    auto: "Автогенерация",
    manual: "Ручной масс-постинг",
};

const creativeSourceColor: Record<AdCreativeSource, string> = {
    auto: "processing",
    manual: "success",
};

export const AdCreativesPage: React.FC = () => {
    const navigate = useNavigate();
    const {currentWorkspace, canManageAvitoAccounts} = useCurrentWorkspace();
    const [modal, contextHolder] = Modal.useModal();

    const [page, setPage] = useState(1);
    const [source, setSource] = useState<AdCreativeSource | undefined>();
    const [avitoAccountId, setAvitoAccountId] = useState<number | undefined>();
    const [search, setSearch] = useState("");
    const [filtersDrawerOpen, setFiltersDrawerOpen] = useState(false);

    const queryParams: AdCreativesQueryParams = {
        page,
        page_size: pageSize,
        source,
        avito_account: avitoAccountId,
        search: search.trim() || undefined,
    };

    const creativesQuery = useAdCreativesQuery(queryParams);
    const projectsQuery = useAvitoProjectsQuery();
    const deleteCreativeMutation = useDeleteAdCreativeMutation();
    const extendCreativeMutation = useExtendAdCreativePublicationsMutation();

    const handleDeleteCreative = (creative: AdCreative) => {
        modal.confirm({
            title: "Удалить креатив?",
            content: `Будут удалены все связанные публикации: ${creative.publications_count}. После удаления CSV будет поставлен в очередь на пересборку.`,
            okText: "Удалить",
            okButtonProps: {danger: true},
            cancelText: "Отмена",
            onOk: () => deleteCreativeMutation.mutateAsync(creative.id),
        });
    };

    const handleExtendCreative = (creative: AdCreative) => {
        modal.confirm({
            title: "Продлить публикации креатива?",
            content: `Будет обновлен общий DateEnd креатива. Публикации с индивидуальным DateEnd не изменятся. Связанных публикаций: ${creative.publications_count}.`,
            okText: "Продлить",
            cancelText: "Отмена",
            onOk: () => extendCreativeMutation.mutateAsync(creative.id),
        });
    };
    const resetPage = () => {
        setPage(1);
    };

    const activeFiltersCount = [
        source,
        avitoAccountId,
    ].filter(Boolean).length;

    const resetFilters = () => {
        setSource(undefined);
        setAvitoAccountId(undefined);
        resetPage();
    };

    const creativeDateEndSourceLabel: Record<AdCreative["date_end_source"], string> = {
        creative: "Креатив",
        default: "30 дней",
    };

    const columns: TableProps<AdCreative>["columns"] = [
        {
            title: "Креатив",
            key: "creative",
            width: 420,
            render: (_, creative) => (
                <Space direction="vertical" size={0}>
                    <Text>{creative.title}</Text>
                    <Paragraph
                        type="secondary"
                        ellipsis={{rows: 2, expandable: false}}
                        style={{marginBottom: 0, maxWidth: 520}}
                    >
                        {/* {creative.description} */}
                    </Paragraph>
                </Space>
            ),
        },
        {
            title: "Источник",
            dataIndex: "source",
            key: "source",
            width: 170,
            render: (value: AdCreativeSource) => (
                <Tag color={creativeSourceColor[value]}>
                    {creativeSourceLabel[value]}
                </Tag>
            ),
        },
        {
            title: "Публикации",
            dataIndex: "publications_count",
            key: "publications_count",
            width: 120,
        },
        {
            title: "Окончание",
            key: "date_end",
            width: 120,
            render: (_, creative) => {
                const deadline = getDateDeadlinePresentation(
                    creative.effective_date_end,
                );

                return (
                    <Tooltip
                        title={creativeDateEndSourceLabel[creative.date_end_source]}
                    >
                        <Text style={{color: dateDeadlineColor[deadline.tone]}}>
                            {deadline.text}
                        </Text>
                    </Tooltip>
                );
            },
        },
        {
            title: "Проекты",
            key: "projects",
            width: 160,
            render: (_, creative) => {
                if (creative.projects.length === 0) {
                    return <Text type="secondary">Без проекта</Text>;
                }

                return (
                    <Space wrap size={4}>
                        {creative.projects.map((project) => (
                            <Tag key={project.id}>{project.name}</Tag>

                        ))}
                    </Space>
                );
            },
        },
        {
            title: "Задача",
            key: "task",
            width: 220,
            render: (_, creative) => creative.task_name ?? "Без задачи",
        },
        {
            title: "Пакет",
            key: "batch",
            width: 140,
            render: (_, creative) =>
                creative.batch ? `#${creative.batch}` : "Без пакета",
        },
        {
            title: "Обновлено",
            dataIndex: "updated_at",
            key: "updated_at",
            width: 190,
            render: (value: string) => formatDateTime(value),
        },
        {
            title: "Действия",
            key: "actions",
            width: 144,
            fixed: "right",
            onHeaderCell: () => ({
                style: {
                    paddingLeft: 24,
                    backgroundColor: "#fafafa",
                },
            }),
            onCell: () => ({
                style: {
                    paddingLeft: 24,
                    backgroundColor: "#fafafa",
                },
            }),
            render: (_, creative) => (
                <Space>
                    <Button
                        icon={<CalendarOutlined/>}
                        disabled={!canManageAvitoAccounts}
                        loading={
                            extendCreativeMutation.isPending &&
                            extendCreativeMutation.variables === creative.id
                        }
                        onClick={() => handleExtendCreative(creative)}
                    />

                    <Button
                        icon={<EditOutlined/>}
                        disabled={!canManageAvitoAccounts}
                        onClick={() => navigate(`/ads/creatives/${creative.id}/edit`)}
                    />

                    <Button
                        danger
                        icon={<DeleteOutlined/>}
                        disabled={!canManageAvitoAccounts}
                        loading={deleteCreativeMutation.isPending}
                        onClick={() => handleDeleteCreative(creative)}
                    />
                </Space>
            ),
        },
    ];

    const handleTableChange = (pagination: TablePaginationConfig) => {
        setPage(pagination.current ?? 1);
    };

    if (!currentWorkspace) {
        return (
            <Alert
                type="warning"
                message="Кабинет не выбран"
                description="Выберите кабинет, чтобы смотреть креативы."
                showIcon
            />
        );
    }

    return (
        <Space direction="vertical" size={16} style={{width: "100%"}}>
            {contextHolder}
            <Space direction="vertical" size={0}>
                <Title level={2} style={{margin: 0}}>
                    Креативы
                </Title>
                <Text type="secondary">
                    Общие креативы, созданные задачами автогенерации или ручным масс-постингом.
                    Один креатив размножается в публикации по адресам.
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
                    placeholder="Поиск по заголовку"
                    value={search}
                    style={{width: 320}}
                    onChange={(event) => {
                        setSearch(event.target.value);
                        resetPage();
                    }}
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

            <Table
                rowKey="id"
                columns={columns}
                dataSource={creativesQuery.data?.results ?? []}
                loading={creativesQuery.isLoading}
                onChange={handleTableChange}
                bordered={true}

                tableLayout="fixed"
                scroll={{x: 1800}}
                pagination={{
                    current: page,
                    pageSize,
                    total: creativesQuery.data?.count ?? 0,
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

                    <Select
                        allowClear
                        placeholder="Проект"
                        value={avitoAccountId}
                        style={{width: "100%"}}
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
                </Space>
            </Drawer>
        </Space>
    );
};
