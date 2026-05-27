import React, {useEffect, useMemo, useState} from "react";
import {useNavigate} from "react-router-dom";
import {
    Alert,
    Button,
    Input,
    Select,
    Space,
    Table,
    Tag,
    Typography,
    Tooltip,
    Drawer,
    Form,
    message,
} from "antd";
import type {TablePaginationConfig, TableProps} from "antd";
import {
    CloudDownloadOutlined,
    FileSyncOutlined,
    LinkOutlined,
    SearchOutlined,
    PauseCircleOutlined,
    PlayCircleOutlined,
    StopOutlined,
    EditOutlined,
} from "@ant-design/icons";

import {
    useAvitoAccountAdsQuery,
    useAvitoProjectsQuery,
    useDownloadAvitoCsvMutation,
    useRequestAvitoCsvExportMutation,
    useBulkUpdateAvitoListingDesiredStatusMutation,
    useUpdateAvitoListingMutation,
} from "../../features/avito";
import {useCurrentWorkspace} from "../../features/workspace/model/useCurrentWorkspace";
import type {
    AvitoAccountAd,
    AvitoAccountAdsQueryParams,
    AvitoListingDesiredStatus,
    AvitoExportStatus,
    JsonObject,
    UpdateAvitoListingRequest,
} from "../../entities/avito/types";

interface ListingEditFormValues {
    title: string;
    description: string;
    address: string;
    desired_status: "publish" | "pause" | "archive";
    management_status: "observed" | "managed" | "out_of_sync";
    image_urls_text: string;
    base_data_json: string;
    option_data_json: string;
}

const stringifyJsonForForm = (value: JsonObject): string =>
    JSON.stringify(value ?? {}, null, 2);

const parseJsonObject = (value: string, fieldLabel: string): JsonObject => {
    const parsed = JSON.parse(value || "{}");

    if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") {
        throw new Error(`${fieldLabel} должен быть JSON-объектом`);
    }

    return parsed as JsonObject;
};

const stringifyImageUrlsForForm = (imageUrls: string[]): string =>
    imageUrls.join("\n");

const parseImageUrls = (value: string): string[] =>
    value
        .split(/\r?\n/)
        .map((item) => item.trim())
        .filter(Boolean);

const {Title, Text} = Typography;

const pageSize = 50;

const entityTypeLabel: Record<string, string> = {
    avito_listing: "Avito",
    ad_publication: "Публикация",
};

const entityTypeColor: Record<string, string> = {
    avito_listing: "blue",
    ad_publication: "purple",
};

type AutoloadState = "publish" | "pause" | "archive" | "error" | "draft" | "unknown";

const csvExportStatusLabel: Record<AvitoExportStatus, string> = {
    clean: "Готов",
    dirty: "Нужно обновить",
    queued: "В очереди",
    exporting: "Формируется",
    error: "Ошибка",
};

const csvExportStatusColor: Record<AvitoExportStatus, string> = {
    clean: "success",
    dirty: "warning",
    queued: "processing",
    exporting: "processing",
    error: "error",
};

const autoloadStateLabel: Record<AutoloadState, string> = {
    publish: "Выгружается",
    pause: "Пауза",
    archive: "Архив",
    error: "Ошибка",
    draft: "Черновик",
    unknown: "Неизвестно",
};

const autoloadStateColor: Record<AutoloadState, string> = {
    publish: "success",
    pause: "warning",
    archive: "default",
    error: "error",
    draft: "processing",
    unknown: "default",
};

const managementStatusLabel: Record<string, string> = {
    observed: "Наблюдаем",
    managed: "Управляется",
    out_of_sync: "Расхождение",
};

const getAutoloadState = (item: AvitoAccountAd): AutoloadState => {
    if (item.has_errors || item.status === "error") {
        return "error";
    }

    if (item.entity_type === "ad_publication") {
        if (item.status === "active") return "publish";
        if (item.status === "paused") return "pause";
        if (item.status === "archived") return "archive";
        if (item.status === "draft") return "draft";

        return "unknown";
    }

    if (item.desired_status === "publish") return "publish";
    if (item.desired_status === "pause") return "pause";
    if (item.desired_status === "archive") return "archive";

    return "unknown";
};

export const AvitoAdsPage: React.FC = () => {

    const [editForm] = Form.useForm<ListingEditFormValues>();
    const [editingListing, setEditingListing] = useState<AvitoAccountAd | null>(null);
    const updateListingMutation = useUpdateAvitoListingMutation();

    const {currentWorkspace} = useCurrentWorkspace();
    const navigate = useNavigate();
    const [page, setPage] = useState(1);
    const [avitoAccountId, setAvitoAccountId] = useState<number | null>(null);
    const [entityType, setEntityType] =
        useState<AvitoAccountAdsQueryParams["entity_type"]>("");
    const [hasAvitoId, setHasAvitoId] =
        useState<AvitoAccountAdsQueryParams["has_avito_id"]>("");
    const [hasErrors, setHasErrors] =
        useState<AvitoAccountAdsQueryParams["has_errors"]>("");
    const [search, setSearch] = useState("");
    const [selectedListingIds, setSelectedListingIds] = useState<number[]>([]);

    const [isExportPollingEnabled, setIsExportPollingEnabled] = useState(false);

    const projectsQuery = useAvitoProjectsQuery({
        refetchInterval: isExportPollingEnabled ? 3000 : false,
    });


    const requestCsvExportMutation = useRequestAvitoCsvExportMutation();
    const downloadCsvMutation = useDownloadAvitoCsvMutation();
    const bulkDesiredStatusMutation = useBulkUpdateAvitoListingDesiredStatusMutation();

    const selectedAvitoAccount = (projectsQuery.data ?? []).find(
        (account) => account.id === avitoAccountId,
    );

    const isCsvExportInProgress =
        selectedAvitoAccount?.export_status === "queued" ||
        selectedAvitoAccount?.export_status === "exporting";

    const isCsvReady =
        selectedAvitoAccount?.export_status === "clean" &&
        Boolean(selectedAvitoAccount.export_file_path);

    useEffect(() => {
        if (!editingListing) {
            editForm.resetFields();
            return;
        }

        editForm.setFieldsValue({
            title: editingListing.title ?? "",
            description: editingListing.description ?? "",
            address: editingListing.address ?? "",
            desired_status: editingListing.desired_status ?? "publish",
            management_status: editingListing.management_status ?? "managed",
            image_urls_text: stringifyImageUrlsForForm(editingListing.image_urls),
            base_data_json: stringifyJsonForForm(editingListing.base_data),
            option_data_json: stringifyJsonForForm(editingListing.option_data),
        });
    }, [editForm, editingListing]);

    useEffect(() => {
        if (isCsvExportInProgress && !isExportPollingEnabled) {
            setIsExportPollingEnabled(true);
        }
    }, [isCsvExportInProgress, isExportPollingEnabled]);

    useEffect(() => {
        if (!isExportPollingEnabled || !selectedAvitoAccount) {
            return;
        }

        if (!isCsvExportInProgress) {
            setIsExportPollingEnabled(false);
        }
    }, [isCsvExportInProgress, isExportPollingEnabled, selectedAvitoAccount]);

    useEffect(() => {
        if (avitoAccountId !== null) {
            return;
        }

        const firstAccount = projectsQuery.data?.[0];

        if (firstAccount) {
            setAvitoAccountId(firstAccount.id);
        }
    }, [avitoAccountId, projectsQuery.data]);

    const queryParams = useMemo<AvitoAccountAdsQueryParams>(
        () => ({
            page,
            page_size: pageSize,
            entity_type: entityType,
            has_avito_id: hasAvitoId,
            has_errors: hasErrors,
            search: search.trim(),
        }),
        [entityType, hasAvitoId, hasErrors, page, search],
    );

    const adsQuery = useAvitoAccountAdsQuery(avitoAccountId, queryParams);

    const rowSelection: TableProps<AvitoAccountAd>["rowSelection"] = {
        selectedRowKeys: selectedListingIds.map((id) => `avito_listing-${id}`),
        onChange: (_, selectedRows) => {
            setSelectedListingIds(
                selectedRows
                    .filter((item) => item.entity_type === "avito_listing")
                    .map((item) => item.id),
            );
        },
        getCheckboxProps: (item) => ({
            disabled:
                item.entity_type !== "avito_listing" ||
                item.avito_account !== avitoAccountId,
        }),
    };

    const getEditAction = (item: AvitoAccountAd) => {
        if (item.entity_type === "ad_publication" && item.publication) {
            return {
                disabled: false,
                tooltip: "Редактировать публикацию",
                onClick: () => navigate(`/ads/publications/${item.publication}/edit`),
            };
        }

        if (item.entity_type === "avito_listing" && item.source === "avito_excel") {
            return {
                disabled: false,
                tooltip: "Редактировать импортированное Avito-объявление",
                onClick: () => setEditingListing(item),
            };
        }

        if (item.entity_type === "avito_listing" && item.publication) {
            return {
                disabled: false,
                tooltip: "Редактировать связанную публикацию",
                onClick: () => navigate(`/ads/publications/${item.publication}/edit`),
            };
        }

        return {
            disabled: true,
            tooltip: "Это объявление пока нельзя редактировать из общего списка",
            onClick: undefined,
        };
    };


    const resetPage = () => {
        setPage(1);
        setSelectedListingIds([]);
    };

    const handleTableChange = (pagination: TablePaginationConfig) => {
        setPage(pagination.current ?? 1);
    };

    const getAutoloadErrorMessage = (item: AvitoAccountAd): string | null => {
        const message = item.autoload_error?.message;

        if (message === null || message === undefined || message === "") {
            return null;
        }

        return String(message);
    };

    const handleCloseEditListing = () => {
        if (updateListingMutation.isPending) {
            return;
        }

        setEditingListing(null);
    };

    const handleSubmitEditListing = async () => {
        if (!editingListing) {
            return;
        }

        const values = await editForm.validateFields();

        let baseData: JsonObject;
        let optionData: JsonObject;

        try {
            baseData = parseJsonObject(values.base_data_json, "base_data");
            optionData = parseJsonObject(values.option_data_json, "option_data");
        } catch (error) {
            message.error(error instanceof Error ? error.message : "Некорректный JSON");
            return;
        }

        const payload: UpdateAvitoListingRequest = {
            title: values.title,
            description: values.description,
            address: values.address,
            desired_status: values.desired_status,
            management_status: values.management_status,
            base_data: baseData,
            option_data: optionData,
            image_urls: parseImageUrls(values.image_urls_text),
        };

        updateListingMutation.mutate(
            {
                listingId: editingListing.id,
                avitoAccountId: editingListing.avito_account,
                data: payload,
            },
            {
                onSuccess: () => {
                    setEditingListing(null);
                },
            },
        );
    };

    const handleRequestCsvExport = () => {
        if (!avitoAccountId) {
            return;
        }

        requestCsvExportMutation.mutate(
            {
                avitoAccountId,
            },
            {
                onSuccess: () => {
                    setIsExportPollingEnabled(true);
                },
            },
        );
    };

    const handleDownloadCsv = () => {
        if (!avitoAccountId) {
            return;
        }

        downloadCsvMutation.mutate({
            avitoAccountId,
            fileName: selectedAvitoAccount
                ? `${selectedAvitoAccount.name}_avito_autoload.csv`
                : `avito-account-${avitoAccountId}.csv`,
        });
    };

    const handleBulkDesiredStatus = (nextStatus: AvitoListingDesiredStatus) => {
        if (!avitoAccountId || selectedListingIds.length === 0) {
            return;
        }

        bulkDesiredStatusMutation.mutate(
            {
                avitoAccountId,
                listingIds: selectedListingIds,
                desiredStatus: nextStatus,
            },
            {
                onSuccess: () => {
                    setSelectedListingIds([]);
                },
            },
        );
    };


    const columns: TableProps<AvitoAccountAd>["columns"] = [
        {
            title: "Тип",
            dataIndex: "entity_type",
            key: "entity_type",
            width: 100,
            render: (value: string) => (
                <Tag color={entityTypeColor[value] ?? "default"}>
                    {entityTypeLabel[value] ?? value}
                </Tag>
            ),
        },
        {
            title: "Название",
            dataIndex: "title",
            key: "title",
            width: 400,
            render: (value: string | null, item) => (
                <Space orientation="vertical" size={0}>
                    <Text strong>{value || "Без названия"}</Text>
                    <Text type="secondary">
                        row_id: {item.row_id || "не задан"}
                    </Text>
                    {item.url && (
                        <Button
                            type="link"
                            size="small"
                            href={item.url}
                            target="_blank"
                            rel="noreferrer"
                            icon={<LinkOutlined/>}
                            style={{padding: 0}}
                        >
                            Открыть на Avito
                        </Button>
                    )}
                </Space>
            ),
        },
        {
            title: "Avito ID",
            dataIndex: "avito_id",
            key: "avito_id",
            width: 150,
            render: (value: string | null) =>
                value ? <Text copyable>{value}</Text> : <Tag>Нет</Tag>,
        },
        {
            title: "Статус",
            dataIndex: "status",
            key: "status",
            width: 100,
            render: (value: string | null, item) => {
                const errorMessage = getAutoloadErrorMessage(item);

                return (
                    <Space orientation="vertical" size={0}>
                        <Tag color={item.has_errors ? "error" : "processing"}>
                            {value || "Неизвестно"}
                        </Tag>
                        {errorMessage && (
                            <Text type="danger" style={{fontSize: 12}}>
                                {errorMessage}
                            </Text>
                        )}
                    </Space>
                );
            },
        },
        {
            title: "Управление",
            key: "management_status",
            width: 130,
            render: (_, item) =>
                item.management_status ? (
                    <Tag color={item.management_status === "managed" ? "success" : "warning"}>
                        {managementStatusLabel[item.management_status] ?? item.management_status}
                    </Tag>
                ) : (
                    <Tag>Не связано</Tag>
                ),
        },
        {
            title: "Автозагрузка",
            key: "autoload_state",
            width: 150,
            render: (_, item) => {
                const state = getAutoloadState(item);

                return (
                    <Tag color={autoloadStateColor[state]}>
                        {autoloadStateLabel[state]}
                    </Tag>
                );
            },
        },
        {
            title: "Адрес",
            dataIndex: "address",
            key: "address",
            width: 260,
            render: (value: string) => value || "Не указан",
        },
        {
            title: "Источник",
            dataIndex: "source",
            key: "source",
            width: 140,
            render: (value: string) => <Tag>{value}</Tag>,
        },
        {
            title: "Avito-аккаунт",
            dataIndex: "avito_account_name",
            key: "avito_account_name",
            width: 170,
        },
        {
            title: "Действия",
            key: "actions",
            width: 140,
            fixed: "right",
            render: (_, item) => {
                const action = getEditAction(item);

                return (
                    <Tooltip title={action.tooltip}>
                        <Button
                            size="small"
                            icon={<EditOutlined/>}
                            disabled={action.disabled}
                            onClick={action.onClick}
                        >
                            Изменить
                        </Button>
                    </Tooltip>
                );
            },
        },
    ];

    if (!currentWorkspace) {
        return (
            <Alert
                type="warning"
                message="Кабинет не выбран"
                description="Выберите кабинет, чтобы смотреть объявления."
                showIcon
            />
        );
    }

    return (
        <Space orientation="vertical" size={16} style={{width: "100%"}}>
            <Space orientation="vertical" size={0}>
                <Title level={2} style={{margin: 0}}>
                    Все объявления
                </Title>
                <Text type="secondary">
                    Единый список: реальные объявления Avito и публикации сервиса, которые еще не связаны с Avito ID.
                </Text>
            </Space>

            <Space wrap>
                <Select
                    style={{width: 220}}
                    placeholder="Avito-аккаунт"
                    loading={projectsQuery.isLoading}
                    value={avitoAccountId ?? undefined}
                    options={(projectsQuery.data ?? []).map((account) => ({
                        label: account.name,
                        value: account.id,
                    }))}
                    onChange={(value) => {
                        setAvitoAccountId(value);
                        resetPage();
                    }}
                />
                {selectedAvitoAccount && (
                    <Tag
                        color={csvExportStatusColor[selectedAvitoAccount.export_status]}
                        style={{
                            height: 32,
                            display: "inline-flex",
                            alignItems: "center",
                            marginInlineEnd: 0,
                            paddingInline: 12,
                            fontWeight: 700,
                            border: 1,
                            borderStyle: "solid",
                        }}
                    >
                        CSV: {csvExportStatusLabel[selectedAvitoAccount.export_status]}
                    </Tag>
                )}

                {selectedAvitoAccount?.export_error && (
                    <Text type="danger">
                        {selectedAvitoAccount.export_error}
                    </Text>
                )}
                <Button
                    icon={<FileSyncOutlined/>}
                    disabled={!avitoAccountId || isCsvExportInProgress}
                    loading={requestCsvExportMutation.isPending || isCsvExportInProgress}
                    onClick={handleRequestCsvExport}
                >
                    {isCsvExportInProgress ? "CSV формируется" : "Сформировать CSV"}
                </Button>

                <Button
                    icon={<CloudDownloadOutlined/>}
                    disabled={!avitoAccountId || !isCsvReady}
                    loading={downloadCsvMutation.isPending}
                    onClick={handleDownloadCsv}
                >
                    Скачать CSV
                </Button>

                <Button
                    icon={<PlayCircleOutlined/>}
                    disabled={!avitoAccountId || selectedListingIds.length === 0}
                    loading={bulkDesiredStatusMutation.isPending}
                    onClick={() => handleBulkDesiredStatus("publish")}
                >

                </Button>

                <Button
                    icon={<PauseCircleOutlined/>}
                    disabled={!avitoAccountId || selectedListingIds.length === 0}
                    loading={bulkDesiredStatusMutation.isPending}
                    onClick={() => handleBulkDesiredStatus("pause")}
                >

                </Button>

                <Button
                    icon={<StopOutlined/>}
                    disabled={!avitoAccountId || selectedListingIds.length === 0}
                    loading={bulkDesiredStatusMutation.isPending}
                    onClick={() => handleBulkDesiredStatus("archive")}
                >

                </Button>

                <Text type="secondary">
                    Выбрано Avito-объявлений: {selectedListingIds.length}
                </Text>
            </Space>

            <Space wrap>


                <Input
                    allowClear
                    prefix={<SearchOutlined/>}
                    placeholder="Название, адрес, row_id, Avito ID"
                    style={{width: 340}}
                    value={search}
                    onChange={(event) => {
                        setSearch(event.target.value);
                        resetPage();
                    }}
                />

                <Select
                    style={{width: 190}}
                    value={entityType}
                    options={[
                        {label: "Все типы", value: ""},
                        {label: "Avito", value: "avito_listing"},
                        {label: "Публикации", value: "ad_publication"},
                    ]}
                    onChange={(value) => {
                        setEntityType(value);
                        resetPage();
                    }}
                />

                <Select
                    style={{width: 190}}
                    value={hasAvitoId}
                    options={[
                        {label: "Любой Avito ID", value: ""},
                        {label: "Есть Avito ID", value: "1"},
                        {label: "Нет Avito ID", value: "0"},
                    ]}
                    onChange={(value) => {
                        setHasAvitoId(value);
                        resetPage();
                    }}
                />

                <Select
                    style={{width: 170}}
                    value={hasErrors}
                    options={[
                        {label: "Все ошибки", value: ""},
                        {label: "Только ошибки", value: "1"},
                        {label: "Без ошибок", value: "0"},
                    ]}
                    onChange={(value) => {
                        setHasErrors(value);
                        resetPage();
                    }}
                />


            </Space>

            {!avitoAccountId && (
                <Alert
                    type="info"
                    showIcon
                    message="Выберите Avito-аккаунт"
                    description="Общий список объявлений строится для конкретного Avito-аккаунта."
                />
            )}

            <Table<AvitoAccountAd>
                rowKey={(item) => `${item.entity_type}-${item.id}`}
                columns={columns}
                rowSelection={rowSelection}
                dataSource={adsQuery.data?.results ?? []}
                loading={adsQuery.isLoading || adsQuery.isFetching}
                scroll={{x: 1600}}
                pagination={{
                    current: page,
                    pageSize,
                    total: adsQuery.data?.count ?? 0,
                    showSizeChanger: false,
                }}
                onChange={handleTableChange}
            />

            <Drawer
                title="Редактирование Avito-объявления"
                open={editingListing !== null}
                width={720}
                onClose={handleCloseEditListing}
                extra={
                    <Space>
                        <Button onClick={handleCloseEditListing}>
                            Отмена
                        </Button>
                        <Button
                            type="primary"
                            loading={updateListingMutation.isPending}
                            onClick={handleSubmitEditListing}
                        >
                            Сохранить
                        </Button>
                    </Space>
                }
            >
                <Form form={editForm} layout="vertical">
                    <Form.Item
                        name="title"
                        label="Название"
                        rules={[{required: true, message: "Введите название"}]}
                    >
                        <Input/>
                    </Form.Item>

                    <Form.Item name="description" label="Описание">
                        <Input.TextArea rows={6}/>
                    </Form.Item>

                    <Form.Item name="address" label="Адрес">
                        <Input/>
                    </Form.Item>

                    <Form.Item name="desired_status" label="Автозагрузка">
                        <Select
                            options={[
                                {label: "Выгружать", value: "publish"},
                                {label: "Пауза", value: "pause"},
                                {label: "Архив", value: "archive"},
                            ]}
                        />
                    </Form.Item>

                    <Form.Item name="management_status" label="Статус управления">
                        <Select
                            options={[
                                {label: "Управляется", value: "managed"},
                                {label: "Расхождение", value: "out_of_sync"},
                                {label: "Наблюдаем", value: "observed"},
                            ]}
                        />
                    </Form.Item>

                    <Form.Item name="image_urls_text" label="Ссылки на фото">
                        <Input.TextArea rows={4}/>
                    </Form.Item>

                    <Form.Item name="base_data_json" label="base_data">
                        <Input.TextArea rows={8} style={{fontFamily: "monospace"}}/>
                    </Form.Item>

                    <Form.Item name="option_data_json" label="option_data">
                        <Input.TextArea rows={8} style={{fontFamily: "monospace"}}/>
                    </Form.Item>
                </Form>
            </Drawer>
        </Space>
    );
};