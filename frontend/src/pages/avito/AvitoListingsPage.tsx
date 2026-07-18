import React, {useEffect, useRef, useState} from "react";
import {
    CloudDownloadOutlined,
    FileSyncOutlined,
    LinkOutlined,
    SearchOutlined,
    CheckCircleOutlined,
    EyeOutlined,
    UploadOutlined,
    EditOutlined,
    ReloadOutlined,
    CalendarOutlined
} from "@ant-design/icons";
import {
    Alert,
    Button,
    Card,
    Col,
    Input,
    Row,
    Select,
    Space,
    message,
    Statistic,
    Table,
    Tag,
    Typography,
    Drawer,
    Form,
    Tooltip
} from "antd";

import type {
    AvitoListing,
    AvitoListingsQueryParams,
    AvitoExcelImportPreviewResponse,
    JsonObject,
    UpdateAvitoListingRequest,
    AvitoListingUnmappedColumnSummary,
    AvitoAdLifecycleAction
} from "../../entities/avito/types";
import {
    useAvitoListingsQuery,
    useAvitoProjectsQuery,
    useAvitoListingLifecycleReportQuery,
    useDownloadAvitoCsvMutation,
    useRequestAvitoCsvExportMutation,
    useBulkUpdateAvitoAdsLifecycleMutation,
    useApplyAvitoExcelImportMutation,
    usePreviewAvitoExcelImportMutation,
    useUpdateAvitoListingMutation,
    useAvitoListingUnmappedSummaryQuery,
    useRemapAvitoListingImportFieldsMutation,
    AdLifecycleBulkActions,
    useExtendAvitoListingMutation
} from "../../features/avito";
import {useCurrentWorkspace} from "../../features/workspace/model/useCurrentWorkspace";
import {
    dateDeadlineColor,
    getDateDeadlinePresentation,
} from "../../shared/lib/formatDateTime";
import type {
    TablePaginationConfig,
    TableProps,
} from "antd";
import type {TableRowSelection} from "antd/es/table/interface";

const {Title, Text} = Typography;

const pageSize = 50;

const statusColorByValue: Record<string, string> = {
    active: "success",
    removed: "default",
    blocked: "error",
    rejected: "error",
    old: "warning"
}

const managementStatusLabel: Record<string, string> = {
    observed: "Наблюдаем",
    managed: "Управляется",
    out_of_sync: "Расхождение",
};

const desiredStatusLabel: Record<string, string> = {
    publish: "Публиковать",
    pause: "Пауза",
    archive: "Архив",
};

const desiredStatusColor: Record<string, string> = {
    publish: "success",
    pause: "warning",
    archive: "default",
};

interface ListingEditFormValues {
    title: string;
    description: string;
    address: string;
    desired_status: AvitoListing["desired_status"];
    management_status: AvitoListing["management_status"];
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

const getFileKey = (file: File): string =>
    `${file.name}-${file.size}-${file.lastModified}`;

export const AvitoListingsPage: React.FC = () => {
    const {currentWorkspace} = useCurrentWorkspace()

    const [editForm] = Form.useForm<ListingEditFormValues>();
    const [editingListing, setEditingListing] = useState<AvitoListing | null>(null);

    const excelFileInputRef = useRef<HTMLInputElement>(null);
    const [excelFile, setExcelFile] = useState<File | null>(null);
    const [excelPreview, setExcelPreview] =
        useState<AvitoExcelImportPreviewResponse | null>(null);
    const [previewedFileKey, setPreviewedFileKey] = useState<string | null>(null);

    const [page, setPage] = useState(1);
    const [avitoAccountId, setAvitoAccountId] = useState<number | undefined>();
    const [status, setStatus] = useState<string | undefined>();
    const [search, setSearch] = useState("");
    const [source, setSource] = useState<AvitoListingsQueryParams["source"]>("avito_excel");
    const [managementStatus, setManagementStatus] =
        useState<AvitoListingsQueryParams["management_status"]>("managed");
    const [desiredStatus, setDesiredStatus] =
        useState<AvitoListingsQueryParams["desired_status"]>("publish");
    const [hasUnmapped, setHasUnmapped] = useState<boolean | undefined>();
    const [selectedListingIds, setSelectedListingIds] = useState<number[]>([]);

    const queryParams: AvitoListingsQueryParams = {
        page,
        page_size: pageSize,
        avito_account_id: avitoAccountId,
        status,
        search: search.trim() || undefined,
        source,
        management_status: managementStatus,
        desired_status: desiredStatus,
        has_unmapped: hasUnmapped,
    };

    const listingsQuery = useAvitoListingsQuery(queryParams);
    const projectsQuery = useAvitoProjectsQuery()
    const extendListingMutation = useExtendAvitoListingMutation();
    const lifecycleQuery = useAvitoListingLifecycleReportQuery(avitoAccountId, 3);
    const unmappedSummaryQuery = useAvitoListingUnmappedSummaryQuery(avitoAccountId, 30);
    const remapImportFieldsMutation = useRemapAvitoListingImportFieldsMutation();
    const requestCsvExportMutation = useRequestAvitoCsvExportMutation();
    const downloadCsvMutation = useDownloadAvitoCsvMutation();
    const bulkLifecycleMutation = useBulkUpdateAvitoAdsLifecycleMutation();
    const previewExcelImportMutation = usePreviewAvitoExcelImportMutation();
    const applyExcelImportMutation = useApplyAvitoExcelImportMutation();
    const updateListingMutation = useUpdateAvitoListingMutation();

    const selectedAvitoAccount = (projectsQuery.data ?? []).find(
        (account) => account.id === avitoAccountId,
    );

    const isAccountActionDisabled = !avitoAccountId;

    const isExcelPreviewActual =
        excelFile !== null && previewedFileKey === getFileKey(excelFile);

    const canApplyExcelImport =
        avitoAccountId !== undefined &&
        excelFile !== null &&
        excelPreview !== null &&
        isExcelPreviewActual

    useEffect(() => {
        if (!editingListing) {
            editForm.resetFields();
            return;
        }

        editForm.setFieldsValue({
            title: editingListing.title ?? "",
            description: editingListing.description ?? "",
            address: editingListing.address ?? "",
            desired_status: editingListing.desired_status,
            management_status: editingListing.management_status,
            base_data_json: stringifyJsonForForm(editingListing.base_data),
            option_data_json: stringifyJsonForForm(editingListing.option_data),
            image_urls_text: stringifyImageUrlsForForm(editingListing.image_urls),
        });
    }, [editForm, editingListing]);

    const resetPage = () => {
        setPage(1);
    }
    const rowSelection: TableRowSelection<AvitoListing> = {
        selectedRowKeys: selectedListingIds,
        onChange: (selectedRowKeys) => {
            setSelectedListingIds(
                selectedRowKeys
                    .map((key) => Number(key))
                    .filter((key) => Number.isFinite(key)),
            );
        },
        getCheckboxProps: (listing) => ({
            disabled:
                !avitoAccountId ||
                listing.avito_account !== avitoAccountId ||
                listing.source !== "avito_excel",
        }),
    };

    const columns: TableProps<AvitoListing>["columns"] = [
            {
                title: "Avito ID",
                dataIndex: "avito_id",
                key: "avito_id",
                width: 140,
                render: (value: string) => (
                    <Text copyable style={{fontSize: 11}}>
                        {value}
                    </Text>
                ),
            },
            {
                title: "Название",
                dataIndex: "title",
                key: "title",
                width: 520,
                render: (value: string | null, listing) => (
                    <Space orientation="vertical" size={0}>
                        <Text strong>{value || "Без названия"}</Text>
                        {listing.url && (
                            <Button
                                type="link"
                                size="small"
                                icon={<LinkOutlined/>}
                                href={listing.url}
                                target="_blank"
                                rel="noreferrer"
                                style={{padding: 0}}
                            >
                                Открыть на Avito
                            </Button>
                        )}
                    </Space>
                ),
            },
            {
                title: "Статус",
                dataIndex: "status",
                key: "status",
                width: 140,
                render: (value: string | null) => {
                    if (!value) {
                        return <Tag>Неизвестно</Tag>
                    }

                    return (
                        <Tag color={statusColorByValue[value] ?? "processing"}>
                            {value}
                        </Tag>
                    )
                }
            },

            {
                title: "Управление",
                key: "management_status",
                width: 150,
                render: (_, listing) => (
                    <Tag color={listing.management_status === "managed" ? "success" : "warning"}>
                        {managementStatusLabel[listing.management_status] ?? listing.management_status}
                    </Tag>
                ),
            },
            {
                title: "В автозагрузке",
                key: "desired_status",
                width: 150,
                render: (_, listing) => (
                    <Tag color={desiredStatusColor[listing.desired_status] ?? "default"}>
                        {desiredStatusLabel[listing.desired_status] ?? listing.desired_status}
                    </Tag>
                ),
            },
            {
                title: "Окончание",
                key: "date_end",
                width: 150,
                render: (_, listing) => {
                    const deadline = getDateDeadlinePresentation(listing.date_end);

                    return (
                        <Tooltip
                            title={
                                listing.date_end_source === "avito"
                                    ? "Avito"
                                    : "Нет данных"
                            }
                        >
                            <Text
                                style={{
                                    color: dateDeadlineColor[deadline.tone],
                                    fontWeight: 600,
                                }}
                            >
                                {deadline.text}
                            </Text>
                        </Tooltip>
                    );
                },
            },
            {
                title: "Unmapped",
                key: "unmapped_data",
                width: 120,
                render: (_, listing) => {
                    const count = Object.keys(listing.unmapped_data ?? {}).length;

                    return count > 0 ? (
                        <Tag color="warning">{count}</Tag>
                    ) : (
                        <Tag color="success">0</Tag>
                    );
                },
            },
            {
                title: "Адрес",
                dataIndex: "address",
                key: "address",
                width: 280,
                render: (value: string) => value || "Не указан",
            },
            {
                title: "Avito-аккаунт",
                dataIndex: "avito_account_name",
                key: "avito_account_name",
                width: 220,
                render: (value: string) => value || "Не указан",
            },
            {
                title: "Публикация",
                key: "publication",
                width: 180,
                render: (_, listing) =>
                    listing.publication ? (
                        <Space orientation="vertical" size={0}>
                            <Text>ID: {listing.publication}</Text>
                            {listing.publication_row_id && (
                                <Text type="secondary" style={{fontSize: 11}}>
                                    row_id: {listing.publication_row_id}
                                </Text>
                            )}
                        </Space>
                    ) : (
                        <Tag>Не связана</Tag>
                    ),
            },
            {
                title: "Последний импорт",
                dataIndex: "last_seen_at",
                key: "last_seen_at",
                width: 260,
                render: (value: string | null) => value ?? "не было"
            },
            {
                title: "Действия",
                key: "actions",
                width: 144,
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
                render: (_, listing) => (
                    <Space>
                        <Tooltip title="Изменить объявление">
                            <Button
                                size="small"
                                icon={<EditOutlined/>}
                                disabled={listing.source !== "avito_excel"}
                                onClick={() => handleOpenEditListing(listing)}
                            />
                        </Tooltip>
                        <Tooltip title="Продлить на 30 дней">
                            <Button
                                size="small"
                                icon={<CalendarOutlined/>}
                                disabled={
                                    listing.source !== "avito_excel" ||
                                    !["managed", "out_of_sync"].includes(listing.management_status)
                                }
                                loading={
                                    extendListingMutation.isPending &&
                                    extendListingMutation.variables?.listingId === listing.id
                                }
                                onClick={() =>
                                    extendListingMutation.mutate({
                                        listingId: listing.id,
                                        avitoAccountId: listing.avito_account,
                                    })
                                }
                            />
                        </Tooltip>
                    </Space>
                ),
            },
        ]
    ;

    const handleRemapImportFields = () => {
        if (!avitoAccountId) {
            return;
        }

        remapImportFieldsMutation.mutate({
            avitoAccountId,
        });
    };

    const handleExcelFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0] ?? null;
        event.target.value = "";

        if (!file) {
            return;
        }

        if (!file.name.toLowerCase().endsWith(".xlsx")) {
            message.error("Загрузите файл XLSX.");
            return;
        }

        setExcelFile(file);
        setExcelPreview(null);
        setPreviewedFileKey(null);
    };

    const handleOpenEditListing = (listing: AvitoListing) => {
        setEditingListing(listing);
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

        const imageUrls = parseImageUrls(values.image_urls_text);


        const payload: UpdateAvitoListingRequest = {
            title: values.title,
            description: values.description,
            address: values.address,
            desired_status: values.desired_status,
            management_status: values.management_status,
            base_data: baseData,
            option_data: optionData,
            image_urls: imageUrls,
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

    const handlePreviewExcelImport = () => {
        if (!avitoAccountId || !excelFile) {
            return;
        }

        previewExcelImportMutation.mutate(
            {
                avitoAccountId,
                file: excelFile,
            },
            {
                onSuccess: (result) => {
                    setExcelPreview(result);
                    setPreviewedFileKey(getFileKey(excelFile));
                },
            },
        );
    };

    const handleApplyExcelImport = () => {
        if (!avitoAccountId || !excelFile || !canApplyExcelImport) {
            return;
        }

        applyExcelImportMutation.mutate(
            {
                avitoAccountId,
                file: excelFile,
            },
            {
                onSuccess: () => {
                    setExcelFile(null);
                    setExcelPreview(null);
                    setPreviewedFileKey(null);
                    setSelectedListingIds([]);
                    setPage(1);
                },
            },
        );
    };
    const handleTableChange = (pagination: TablePaginationConfig) => {
        setPage(pagination.current ?? 1)
    }

    const handleRequestCsvExport = () => {
        if (!avitoAccountId) {
            return;
        }

        requestCsvExportMutation.mutate({
            avitoAccountId,
        });
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

    const handleBulkLifecycle = (action: AvitoAdLifecycleAction) => {
        if (!avitoAccountId || selectedListingIds.length === 0) {
            return;
        }

        bulkLifecycleMutation.mutate(
            {
                avitoAccountId,
                items: selectedListingIds.map((id) => ({
                    entity_type: "avito_listing",
                    id,
                })),
                action,
            },
            {
                onSuccess: () => {
                    setSelectedListingIds([]);
                },
            },
        );
    };

    if (!currentWorkspace) {
        return (
            <Alert
                type="warning"
                message="Кабинет не выбран"
                description="Выберите кабинет, чтобы смотреть объявления Avito."
                showIcon
            />
        );
    }

    return (
        <Space orientation="vertical" size={16} style={{width: "100%"}}>
            <Space orientation="vertical" size={0}>
                <Title level={2} style={{margin: 0}}>
                    Объявления Avito
                </Title>
                <Text type="secondary">
                    Импортированные объявления из Avito. Таблица читает локальную базу и не делает запросы в Avito API.
                </Text>
            </Space>

            {!avitoAccountId && (
                <Alert
                    type="info"
                    showIcon
                    message="Выберите Avito-аккаунт"
                    description="Lifecycle report, CSV export и массовые действия работают для конкретного Avito-аккаунта."
                />
            )}

            <Card size="small" title="Импорт XLSX из кабинета Avito">
                <Space orientation="vertical" size={16} style={{width: "100%"}}>
                    <input
                        ref={excelFileInputRef}
                        type="file"
                        accept=".xlsx"
                        style={{display: "none"}}
                        onChange={handleExcelFileChange}
                    />

                    <Space wrap size="middle">
                        <Button
                            icon={<UploadOutlined/>}
                            disabled={!avitoAccountId}
                            onClick={() => excelFileInputRef.current?.click()}
                        >
                            Выбрать XLSX
                        </Button>

                        <Button
                            icon={<EyeOutlined/>}
                            disabled={!avitoAccountId || !excelFile}
                            loading={previewExcelImportMutation.isPending}
                            onClick={handlePreviewExcelImport}
                        >
                            Предпросмотр
                        </Button>

                        <Button
                            type="primary"
                            icon={<CheckCircleOutlined/>}
                            disabled={!canApplyExcelImport}
                            loading={applyExcelImportMutation.isPending}
                            onClick={handleApplyExcelImport}
                        >
                            Импортировать
                        </Button>

                        <Text type="secondary">
                            {excelFile ? excelFile.name : "Файл не выбран"}
                        </Text>
                    </Space>

                    {excelPreview && !isExcelPreviewActual && (
                        <Alert
                            type="warning"
                            showIcon
                            message="Файл изменился"
                            description="После выбора нового файла нужно заново выполнить предпросмотр."
                        />
                    )}

                    {excelPreview && (
                        <Row gutter={[12, 12]}>
                            <Col xs={12} md={6}>
                                <Statistic title="Листов" value={excelPreview.total_sheets}/>
                            </Col>
                            <Col xs={12} md={6}>
                                <Statistic title="Строк" value={excelPreview.total_rows}/>
                            </Col>
                            <Col xs={12} md={6}>
                                <Statistic
                                    title="Строк с ошибками"
                                    value={excelPreview.rows_with_errors}
                                    valueStyle={{
                                        color: excelPreview.rows_with_errors > 0 ? "#cf1322" : "#3f8600",
                                    }}
                                />
                            </Col>
                            <Col xs={12} md={6}>
                                <Statistic
                                    title="Неразобранных колонок"
                                    value={excelPreview.unmapped_columns.length}
                                />
                            </Col>
                        </Row>
                    )}

                    {excelPreview && excelPreview.rows_with_errors > 0 && (
                        <Alert
                            type="warning"
                            showIcon
                            message="Часть строк будет пропущена"
                            description={`В файле найдено строк с ошибками: ${excelPreview.rows_with_errors}. Остальные объявления можно импортировать.`}
                        />
                    )}

                    {excelPreview && excelPreview.unmapped_columns.length > 0 && (
                        <Alert
                            type="info"
                            showIcon
                            message="Есть неразобранные колонки"
                            description={excelPreview.unmapped_columns.slice(0, 20).join(", ")}
                        />
                    )}

                    {excelPreview && excelPreview.rows.length > 0 && (
                        <Table
                            size="small"
                            rowKey={(row) => `${row.sheet_name}-${row.row_number}`}
                            pagination={false}
                            dataSource={excelPreview.rows.slice(0, 5)}
                            columns={[
                                {
                                    title: "Лист",
                                    dataIndex: "sheet_name",
                                    key: "sheet_name",
                                    width: 180,
                                },
                                {
                                    title: "Строка",
                                    dataIndex: "row_number",
                                    key: "row_number",
                                    width: 90,
                                },
                                {
                                    title: "Avito ID",
                                    dataIndex: "avito_id",
                                    key: "avito_id",
                                    width: 140,
                                    render: (value: string | null) => value || "нет",
                                },
                                {
                                    title: "Row ID",
                                    dataIndex: "row_id",
                                    key: "row_id",
                                    width: 140,
                                    render: (value: string | null) => value || "нет",
                                },
                                {
                                    title: "Название",
                                    dataIndex: "title",
                                    key: "title",
                                    render: (value: string | null) => value || "Без названия",
                                },
                                {
                                    title: "Ошибки",
                                    dataIndex: "errors",
                                    key: "errors",
                                    width: 220,
                                    render: (errors: string[]) =>
                                        errors.length > 0 ? (
                                            <Text type="danger">{errors.join(", ")}</Text>
                                        ) : (
                                            <Text type="secondary">нет</Text>
                                        ),
                                },
                            ]}
                        />
                    )}
                </Space>
            </Card>

            <Card size="small">
                <Space orientation="vertical" size={16} style={{width: "100%"}}>
                    <Space wrap size="middle">
                        <Button
                            type="primary"
                            icon={<FileSyncOutlined/>}
                            disabled={isAccountActionDisabled}
                            loading={requestCsvExportMutation.isPending}
                            onClick={handleRequestCsvExport}
                        >
                            Сформировать CSV
                        </Button>

                        <Button
                            icon={<CloudDownloadOutlined/>}
                            disabled={isAccountActionDisabled}
                            loading={downloadCsvMutation.isPending}
                            onClick={handleDownloadCsv}
                        >
                            Скачать CSV
                        </Button>

                        {selectedAvitoAccount && (
                            <Text type="secondary">
                                CSV статус: {selectedAvitoAccount.export_status}
                                {selectedAvitoAccount.last_exported_at
                                    ? `, последняя выгрузка: ${selectedAvitoAccount.last_exported_at}`
                                    : ""}
                            </Text>
                        )}
                    </Space>

                    <Row gutter={[12, 12]}>
                        <Col xs={12} md={6}>
                            <Statistic
                                title="Проверено"
                                value={lifecycleQuery.data?.total_checked ?? 0}
                                loading={lifecycleQuery.isLoading}
                            />
                        </Col>
                        <Col xs={12} md={6}>
                            <Statistic
                                title="Истекли"
                                value={lifecycleQuery.data?.expired ?? 0}
                                loading={lifecycleQuery.isLoading}
                                valueStyle={{color: "#cf1322"}}
                            />
                        </Col>
                        <Col xs={12} md={6}>
                            <Statistic
                                title="Истекают за 3 дня"
                                value={lifecycleQuery.data?.expires_soon ?? 0}
                                loading={lifecycleQuery.isLoading}
                                valueStyle={{color: "#d46b08"}}
                            />
                        </Col>
                        <Col xs={12} md={6}>
                            <Statistic
                                title="Активные"
                                value={lifecycleQuery.data?.active_ok ?? 0}
                                loading={lifecycleQuery.isLoading}
                                valueStyle={{color: "#3f8600"}}
                            />
                        </Col>
                    </Row>

                    {lifecycleQuery.data && lifecycleQuery.data.items.length > 0 && (
                        <Alert
                            type="warning"
                            showIcon
                            message="Есть объявления, требующие внимания"
                            description={`Первые проблемные объявления: ${lifecycleQuery.data.items
                                .slice(0, 5)
                                .map((item) => item.row_id || item.avito_id)
                                .join(", ")}`}
                        />
                    )}
                </Space>
            </Card>

            <Card
                size="small"
                title="Неразобранные колонки импорта"
                extra={
                    <Button
                        icon={<ReloadOutlined/>}
                        disabled={!avitoAccountId}
                        loading={remapImportFieldsMutation.isPending}
                        onClick={handleRemapImportFields}
                    >
                        Пересобрать маппинг
                    </Button>
                }
            >
                <Space orientation="vertical" size={12} style={{width: "100%"}}>
                    <Row gutter={[12, 12]}>
                        <Col xs={12} md={6}>
                            <Statistic
                                title="Объявлений с unmapped"
                                value={unmappedSummaryQuery.data?.total_listings_with_unmapped ?? 0}
                                loading={unmappedSummaryQuery.isLoading}
                            />
                        </Col>
                        <Col xs={12} md={6}>
                            <Statistic
                                title="Уникальных колонок"
                                value={unmappedSummaryQuery.data?.total_columns ?? 0}
                                loading={unmappedSummaryQuery.isLoading}
                            />
                        </Col>
                    </Row>

                    <Table<AvitoListingUnmappedColumnSummary>
                        size="small"
                        rowKey="name"
                        pagination={false}
                        loading={unmappedSummaryQuery.isLoading}
                        dataSource={unmappedSummaryQuery.data?.columns ?? []}
                        columns={[
                            {
                                title: "Колонка XLSX",
                                dataIndex: "name",
                                key: "name",
                            },
                            {
                                title: "Объявлений",
                                dataIndex: "count",
                                key: "count",
                                width: 140,
                                sorter: (a, b) => a.count - b.count,
                                defaultSortOrder: "descend",
                            },
                        ]}
                    />

                    <Alert
                        type="info"
                        showIcon
                        message="Как уменьшать unmapped"
                        description="Добавляй или исправляй ProductOptions: option_title_ru должен совпадать с названием колонки XLSX, option_title_en — с техническим названием поля автозагрузки Avito."
                    />
                </Space>
            </Card>

            <Space wrap size="middle">
                <Input
                    allowClear
                    prefix={<SearchOutlined/>}
                    placeholder="Поиск по названию Avito ID"
                    value={search}
                    style={{width: 320}}
                    onChange={(event) => {
                        setSearch(event.target.value);
                        resetPage()
                    }}
                />

                <Select
                    allowClear
                    placeholder="Avito-аккаунт"
                    value={avitoAccountId}
                    style={{width: 260}}
                    loading={projectsQuery.isLoading}
                    options={(projectsQuery.data ?? []).map((project) => ({
                        value: project.id,
                        label: project.name
                    }))}
                    onChange={(value) => {
                        setAvitoAccountId(value);
                        setSelectedListingIds([]);
                        resetPage();
                    }}

                />

                <Select
                    allowClear
                    placeholder="Статус"
                    value={status}
                    style={{width: 180}}
                    options={[
                        {value: "active", label: "active"},
                        {value: "removed", label: "removed"},
                        {value: "blocked", label: "blocked"},
                        {value: "rejected", label: "rejected"},
                        {value: "old", label: "old"},
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
                        {value: "avito_excel", label: "XLSX Avito"},
                        {value: "api", label: "Avito API"},
                        {value: "service", label: "Сервис"},
                    ]}
                    onChange={(value) => {
                        setSource(value);
                        resetPage();
                    }}
                />

                <Select
                    allowClear
                    placeholder="Управление"
                    value={managementStatus}
                    style={{width: 180}}
                    options={[
                        {value: "managed", label: "Управляется"},
                        {value: "observed", label: "Наблюдаем"},
                        {value: "out_of_sync", label: "Расхождение"},
                    ]}
                    onChange={(value) => {
                        setManagementStatus(value);
                        resetPage();
                    }}
                />

                <Select
                    allowClear
                    placeholder="Желаемый статус"
                    value={desiredStatus}
                    style={{width: 180}}
                    options={[
                        {value: "publish", label: "Публиковать"},
                        {value: "pause", label: "Пауза"},
                        {value: "archive", label: "Архив"},
                    ]}
                    onChange={(value) => {
                        setDesiredStatus(value);
                        resetPage();
                    }}
                />

                <Select
                    allowClear
                    placeholder="Неразобранные поля"
                    value={hasUnmapped}
                    style={{width: 210}}
                    options={[
                        {value: true, label: "Есть unmapped"},
                        {value: false, label: "Нет unmapped"},
                    ]}
                    onChange={(value) => {
                        setHasUnmapped(value);
                        resetPage();
                    }}
                />
            </Space>

            <Card size="small">
                <Space wrap size="middle">

                    <AdLifecycleBulkActions
                        selectedCount={selectedListingIds.length}
                        disabled={!avitoAccountId}
                        loading={bulkLifecycleMutation.isPending}
                        onAction={handleBulkLifecycle}
                        onClearSelection={() => setSelectedListingIds([])}
                    />

                    {selectedListingIds.length > 0 && (
                        <Button onClick={() => setSelectedListingIds([])}>
                            Сбросить выбор
                        </Button>
                    )}

                </Space>
            </Card>

            <Table<AvitoListing>
                rowKey="id"
                columns={columns}
                rowSelection={rowSelection}
                dataSource={listingsQuery.data?.results ?? []}
                loading={listingsQuery.isLoading}
                onChange={handleTableChange}
                tableLayout="fixed"
                scroll={{x: 2200}}
                rowHoverable={false}
                pagination={{
                    current: page,
                    pageSize,
                    total: listingsQuery.data?.count ?? 0,
                    showSizeChanger: false
                }}
            />

            <Drawer
                title="Редактирование AvitoListing"
                width={720}
                open={editingListing !== null}
                onClose={handleCloseEditListing}
                destroyOnHidden
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
                <Form
                    form={editForm}
                    layout="vertical"
                    disabled={updateListingMutation.isPending}
                >
                    <Form.Item
                        name="title"
                        label="Название"
                        rules={[{required: true, message: "Введите название"}]}
                    >
                        <Input/>
                    </Form.Item>

                    <Form.Item
                        name="description"
                        label="Описание"
                    >
                        <Input.TextArea rows={8}/>
                    </Form.Item>

                    <Form.Item
                        name="address"
                        label="Адрес"
                    >
                        <Input/>
                    </Form.Item>

                    <Form.Item
                        name="image_urls_text"
                        label="Ссылки на изображения"
                        extra="Одна ссылка на строку. Эти ссылки попадут в ImageUrls в CSV."
                    >
                        <Input.TextArea rows={6} spellCheck={false}/>
                    </Form.Item>

                    <Row gutter={12}>
                        <Col xs={24} md={12}>
                            <Form.Item
                                name="desired_status"
                                label="Желаемый статус"
                                rules={[{required: true, message: "Выберите статус"}]}
                            >
                                <Select
                                    options={[
                                        {value: "publish", label: "Публиковать"},
                                        {value: "pause", label: "Пауза"},
                                        {value: "archive", label: "Архив"},
                                    ]}
                                />
                            </Form.Item>
                        </Col>

                        <Col xs={24} md={12}>
                            <Form.Item
                                name="management_status"
                                label="Статус управления"
                                rules={[{required: true, message: "Выберите статус управления"}]}
                            >
                                <Select
                                    options={[
                                        {value: "managed", label: "Управляется"},
                                        {value: "observed", label: "Наблюдаем"},
                                        {value: "out_of_sync", label: "Расхождение"},
                                    ]}
                                />
                            </Form.Item>
                        </Col>
                    </Row>

                    <Form.Item
                        name="base_data_json"
                        label="base_data"
                        rules={[{required: true, message: "Введите base_data"}]}
                    >
                        <Input.TextArea rows={10} spellCheck={false}/>
                    </Form.Item>

                    <Form.Item
                        name="option_data_json"
                        label="option_data"
                        rules={[{required: true, message: "Введите option_data"}]}
                    >
                        <Input.TextArea rows={10} spellCheck={false}/>
                    </Form.Item>

                    <Form.Item label="unmapped_data">
                        <Input.TextArea
                            rows={8}
                            value={editingListing ? stringifyJsonForForm(editingListing.unmapped_data) : "{}"}
                            readOnly
                            spellCheck={false}
                        />
                    </Form.Item>
                </Form>
            </Drawer>
        </Space>
    )
}
