import React, {useState} from "react";

import {EditOutlined, LinkOutlined, ReloadOutlined, SearchOutlined} from "@ant-design/icons";
import {useNavigate, useSearchParams} from "react-router-dom";
import {
    Alert,
    Button,
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
} from "../../entities/avito/types";
import {
    useAdPublicationsQuery,
    useAvitoProjectsQuery,
    useLinkAvitoPublicationsMutation,
} from "../../features/avito";
import {useCurrentWorkspace} from "../../features/workspace/model/useCurrentWorkspace";

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

const dateTimeFormatter = new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
});

const formatPublicationDateTime = (value: string | null | undefined): string => {
    if (!value) {
        return "не было";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return "не было";
    }

    return dateTimeFormatter.format(date).replace(",", "");
};


export const AdPublicationsPage: React.FC = () => {
    const {currentWorkspace, canManageAvitoAccounts} = useCurrentWorkspace();
    const [page, setPage] = useState(1);
    const [avitoAccountId, setAvitoAccountId] = useState<number | undefined>();
    const [status, setStatus] = useState<AdPublicationStatus | undefined>();
    const [source, setSource] = useState<AdPublicationSource | undefined>();
    const [search, setSearch] = useState("")

    const navigate = useNavigate();
    const [searchParams, setSearchParams] = useSearchParams();

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

    const resetPage = () => {
        setPage(1);
    }

    const clearBatchFilter = () => {
        const nextParams = new URLSearchParams(searchParams);
        nextParams.delete("batch");
        setSearchParams(nextParams);
        setPage(1);
    };

    const selectedProject = (projectsQuery.data ?? []).find(
        (project) => project.id === avitoAccountId
    )

    const columns: TableProps<AdPublication>["columns"] = [
        {
            title: "row_id",
            dataIndex: "row_id",
            key: "row_id",
            width: 210,
            render: (value: string | null) =>
                value ? <Text copyable>{value}</Text> : <Tag>Нет row_id</Tag>,
        },
        {
            title: "Объявление",
            key: "creative",
            render: (_, publication) => (
                <Space orientation="vertical" size={0}>
                    <Text strong>{publication.creative_title}</Text>
                    <Text type="secondary">{publication.address || "Адрес не указан"}</Text>
                </Space>
            ),
        },
        {
            title: "Проект",
            dataIndex: "avito_account_name",
            key: "avito_account_name",
            width: 200,
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
            width: 150,
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
            width: 210,
            render: (_, publication) => (
                <Space orientation="vertical" size={0}>
                    <Text type="secondary" style={{fontSize: 10}}>
                        Последний экспорт: {formatPublicationDateTime(publication.last_exported_at)}
                    </Text>
                    <Text type="secondary" style={{fontSize: 11, fontWeight: "bold"}}>
                        Создано: {formatPublicationDateTime(publication.created_at)}
                    </Text>
                </Space>
            ),
        },

        {
            title: "Действия",
            key: "actions",
            width: 120,
            render: (_, publication) => (
                <Button
                    icon={<EditOutlined/>}
                    disabled={!canManageAvitoAccounts}
                    onClick={() => navigate(`/ads/publications/${publication.id}/edit`)}
                >
                    Изменить
                </Button>
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
                    Публикации CSV
                </Title>
                <Text type="secondary">
                    Строки автозагрузки, созданные из креативов по адресам. Связь с Avito ID появляется после выгрузки и
                    сопоставления.
                </Text>
            </Space>

            <Space wrap size="middle">
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
                    style={{width: 260}}
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

                <Select
                    allowClear
                    placeholder="Статус"
                    value={status}
                    style={{width: 180}}
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
                    style={{width: 180}}
                    options={[
                        {value: "auto", label: "Автогенерация"},
                        {value: "manual", label: "Ручной масс-постинг"},
                    ]}
                    onChange={(value) => {
                        setSource(value);
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
            </Space>

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

            <Table
                rowKey="id"
                columns={columns}
                dataSource={publicationsQuery.data?.results ?? []}
                loading={publicationsQuery.isLoading}
                onChange={handleTableChange}
                pagination={{
                    current: page,
                    pageSize,
                    total: publicationsQuery.data?.count ?? 0,
                    showSizeChanger: false,
                }}
            />
        </Space>
    );


}