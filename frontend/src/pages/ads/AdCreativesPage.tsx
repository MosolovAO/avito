// src/pages/ads/AdCreativesPage.tsx
import React, {useState} from "react";
import {DeleteOutlined, EditOutlined, SearchOutlined} from "@ant-design/icons";
import {
    Alert,
    Button,
    Input,
    Select,
    Space,
    Table,
    Tag,
    Modal,
    Typography,
} from "antd";
import type {TablePaginationConfig, TableProps} from "antd";
import {useNavigate} from "react-router-dom";
import type {
    AdCreative,
    AdCreativeSource,
    AdCreativesQueryParams,
} from "../../entities/avito/types";
import {useAdCreativesQuery, useDeleteAdCreativeMutation} from "../../features/avito";
import {useCurrentWorkspace} from "../../features/workspace/model/useCurrentWorkspace";

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
    const [search, setSearch] = useState("");

    const queryParams: AdCreativesQueryParams = {
        page,
        page_size: pageSize,
        source,
        search: search.trim() || undefined,
    };

    const creativesQuery = useAdCreativesQuery(queryParams);
    const deleteCreativeMutation = useDeleteAdCreativeMutation();


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
    const resetPage = () => {
        setPage(1);
    };

    const columns: TableProps<AdCreative>["columns"] = [
        {
            title: "Креатив",
            key: "creative",
            render: (_, creative) => (
                <Space direction="vertical" size={0}>
                    <Text strong>{creative.title}</Text>
                    <Paragraph
                        type="secondary"
                        ellipsis={{rows: 2, expandable: false}}
                        style={{marginBottom: 0, maxWidth: 520}}
                    >
                        {creative.description}
                    </Paragraph>
                </Space>
            ),
        },
        {
            title: "Источник",
            dataIndex: "source",
            key: "source",
            width: 140,
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
            width: 130,
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
        },
        {
            title: "Действия",
            key: "actions",
            width: 120,
            render: (_, creative) => (
                <Space>
                    <Button
                        icon={<EditOutlined/>}
                        disabled={!canManageAvitoAccounts}
                        onClick={() => navigate(`/ads/creatives/${creative.id}/edit`)}
                    >

                    </Button>

                    <Button
                        danger
                        icon={<DeleteOutlined/>}
                        disabled={!canManageAvitoAccounts}
                        loading={deleteCreativeMutation.isPending}
                        onClick={() => handleDeleteCreative(creative)}
                    >

                    </Button>
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

            <Space wrap size="middle">
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
            </Space>

            <Table
                rowKey="id"
                columns={columns}
                dataSource={creativesQuery.data?.results ?? []}
                loading={creativesQuery.isLoading}
                onChange={handleTableChange}
                pagination={{
                    current: page,
                    pageSize,
                    total: creativesQuery.data?.count ?? 0,
                    showSizeChanger: false,
                }}
            />
        </Space>
    );
};
