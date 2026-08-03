import React, {
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
} from "react";
import {useNavigate} from "react-router-dom";
import {
    Alert,
    AutoComplete,
    Button,
    Col,
    Drawer,
    DatePicker,
    Form,
    Input,
    InputNumber,
    message,
    Row,
    Select,
    Space,
    Spin,
    Table,
    Tag,
    Tooltip,
    Typography,
} from "antd";
import dayjs from "dayjs";
import type {Dayjs} from "dayjs";
import type {FormInstance, TablePaginationConfig, TableProps} from "antd";
import {
    CloudDownloadOutlined,
    EditOutlined,
    EyeOutlined,
    FileSyncOutlined,
    FilterOutlined,
    HeartOutlined,
    LinkOutlined,
    ReloadOutlined,
    SearchOutlined,
    UserOutlined,
    WalletOutlined,
} from "@ant-design/icons";

import {
    dateDeadlineColor,
    getDateDeadlinePresentation,
} from "../../shared/lib/formatDateTime";
import {
    useAvitoAccountAdsQuery,
    useAvitoProjectsQuery,
    useDownloadAvitoCsvMutation,
    useRequestAvitoCsvExportMutation,
    useBulkUpdateAvitoAdsLifecycleMutation,
    useUpdateAvitoListingMutation,
    useUpdateAdPublicationMutation,
    useAdPublicationQuery,
    AdLifecycleBulkActions,
    useImportAvitoDailyStatsMutation,
} from "../../features/avito";
import {useCurrentWorkspace} from "../../features/workspace/model/useCurrentWorkspace";
import type {
    AvitoAccountAd,
    AvitoAccountAdsQueryParams,
    AvitoAdLifecycleAction,
    AvitoExportStatus,
    JsonObject,
    UpdateAvitoListingRequest,
    AdPublicationStatus,
} from "../../entities/avito/types";
import {
    buildPublicationEditInitialValues,
    buildPublicationUpdateRequest,
} from "../../features/avito/lib/adPublicationEditMapper";

import {useQuery} from "@tanstack/react-query";
import type {ProductOption} from "../../entities/product";
import {useProductOptions} from "../../features/product/model/useProductOptions";
import {getProductCategories} from "../../shared/api/products";
import {AVITO_AUTOLOAD_CATEGORY_OPTIONS} from "../../shared/constants/avitoCategories";
import {
    buildOptionData,
    buildOptionFormValues,
    getCreativeAutoloadCategory,
    mergeUnknownOptionData,
    type EditableOptionValue,
} from "../../features/avito/lib/adCreativeFormMapper";

import {
    withoutLegacyDateEnd,
} from "../../features/avito/lib/legacyDateEnd";

interface SelectedAdItem {
    entity_type: AvitoAccountAd["entity_type"];
    id: number;
    canExtend: boolean;
}

interface ListingEditFormValues {
    option_category_id?: number;
    autoload_category: string;
    options: Record<string, EditableOptionValue | undefined>;

    title: string;
    description: string;
    address: string;
    desired_status: "publish" | "pause" | "archive";
    management_status: "observed" | "managed" | "out_of_sync";
    image_urls_text: string;
    base_data_json: string;
    option_data_json: string;
}

interface AdEditFormValues extends ListingEditFormValues {
    status: AdPublicationStatus;
}

type EditingAdState =
    | { type: "avito_listing"; item: AvitoAccountAd }
    | { type: "ad_publication"; item: AvitoAccountAd };

const EMPTY_PRODUCT_OPTIONS: ProductOption[] = [];

const canExtendAd = (item: AvitoAccountAd): boolean => {
    if (item.entity_type === "ad_publication") {
        return item.publication !== null;
    }

    if (item.source === "service") {
        return item.publication !== null;
    }

    return (
        item.source === "avito_excel" &&
        item.management_status !== null &&
        ["managed", "out_of_sync"].includes(item.management_status)
    );
};

const stringifyJsonForForm = (value: JsonObject): string =>
    JSON.stringify(withoutLegacyDateEnd(value), null, 2);

const parseJsonObject = (
    value: string,
    fieldLabel: string,
): JsonObject => {
    const parsed: unknown = JSON.parse(value || "{}");

    if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") {
        throw new Error(`${fieldLabel} должен быть JSON-объектом`);
    }

    return withoutLegacyDateEnd(parsed as JsonObject);
};

const stringifyImageUrlsForForm = (imageUrls: string[]): string =>
    imageUrls.join("\n");

const parseImageUrls = (value: string): string[] =>
    value
        .split(/\r?\n/)
        .map((item) => item.trim())
        .filter(Boolean);

const {Title, Text} = Typography;
const {RangePicker} = DatePicker;

type JsonTextFieldName = "base_data_json" | "option_data_json";

type AvitoAdsOrdering = NonNullable<
    AvitoAccountAdsQueryParams["ordering"]
>;

type AvitoAdsSortField =
    | "date_end"
    | "views"
    | "contacts"
    | "views_to_contacts_conversion";

type SortDirection = "asc" | "desc";

const pageSize = 30;

const DEFAULT_SORT_FIELD: AvitoAdsSortField = "date_end";
const DEFAULT_SORT_DIRECTION: SortDirection = "desc";
const DEFAULT_STATS_DATE_TO = dayjs()
    .subtract(1, "day")
    .startOf("day");
const DEFAULT_STATS_DATE_FROM = DEFAULT_STATS_DATE_TO
    .subtract(29, "day");

const SORT_ORDERINGS: Record<
    AvitoAdsSortField,
    Record<SortDirection, AvitoAdsOrdering>
> = {
    date_end: {
        asc: "date_end",
        desc: "-date_end",
    },
    views: {
        asc: "views",
        desc: "-views",
    },
    contacts: {
        asc: "contacts",
        desc: "-contacts",
    },
    views_to_contacts_conversion: {
        asc: "views_to_contacts_conversion",
        desc: "-views_to_contacts_conversion",
    },
};


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

const dateEndSourceLabel: Record<AvitoAccountAd["date_end_source"], string> = {
    avito: "Avito",
    publication: "Публикация",
    creative: "Креатив",
    default: "30 дней",
    none: "Нет данных",
};

interface JsonObjectInputsProps {
    form: FormInstance<AdEditFormValues>;
    name: JsonTextFieldName;
    title: string;
    emptyText: string;
    excludedKeys?: string[];
}


const parseJsonObjectForInputs = (value: string | undefined): JsonObject => {
    try {
        const parsed = JSON.parse(value || "{}");

        if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") {
            return {};
        }

        return parsed as JsonObject;
    } catch {
        return {};
    }
};

const formatJsonInputValue = (value: unknown): string => {
    if (value === null || value === undefined) {
        return "";
    }

    if (Array.isArray(value)) {
        return value.map(String).join(", ");
    }

    if (typeof value === "object") {
        return JSON.stringify(value);
    }

    return String(value);
};

const coerceJsonInputValue = (previousValue: unknown, rawValue: string): unknown => {
    if (Array.isArray(previousValue)) {
        return rawValue
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean);
    }

    if (typeof previousValue === "number") {
        const numberValue = Number(rawValue.replace(",", "."));
        return Number.isFinite(numberValue) ? numberValue : rawValue;
    }

    if (typeof previousValue === "boolean") {
        if (rawValue === "true") return true;
        if (rawValue === "false") return false;
        return rawValue;
    }

    if (previousValue !== null && typeof previousValue === "object") {
        try {
            return JSON.parse(rawValue);
        } catch {
            return rawValue;
        }
    }

    return rawValue;
};

const JsonObjectInputs: React.FC<JsonObjectInputsProps> = ({
                                                               form,
                                                               name,
                                                               title,
                                                               emptyText,
                                                               excludedKeys = [],
                                                           }) => (
    <Form.Item noStyle shouldUpdate={(prev, next) => prev[name] !== next[name]}>
        {() => {
            const data = parseJsonObjectForInputs(form.getFieldValue(name) as string | undefined);
            const entries = Object.entries(data).filter(
                ([key]) => !excludedKeys.includes(key),
            );

            return (
                <Space direction="vertical" size={12} style={{width: "100%"}}>
                    <Text strong>{title}</Text>


                    {entries.length === 0 ? (
                        <Text type="secondary">{emptyText}</Text>
                    ) : (
                        <Row gutter={[12, 12]}>
                            {entries.map(([key, value]) => (
                                <Col key={key} xs={24} md={12}>
                                    <Form.Item label={key} style={{marginBottom: 0}}>
                                        <Input
                                            value={formatJsonInputValue(value)}
                                            onChange={(event) => {
                                                const nextData = {
                                                    ...data,
                                                    [key]: coerceJsonInputValue(value, event.target.value),
                                                };

                                                form.setFieldValue(name, JSON.stringify(nextData, null, 2));
                                            }}
                                        />
                                    </Form.Item>
                                </Col>
                            ))}
                        </Row>
                    )}
                </Space>
            );
        }}
    </Form.Item>
);

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

    const [editForm] = Form.useForm<AdEditFormValues>();
    const [editingAd, setEditingAd] = useState<EditingAdState | null>(null);
    const editingListing = editingAd?.type === "avito_listing" ? editingAd.item : null;
    const editingPublication = editingAd?.type === "ad_publication" ? editingAd.item : null;
    const editingPublicationId = editingPublication?.publication ?? editingPublication?.id ?? null;
    const updateListingMutation = useUpdateAvitoListingMutation();
    const updatePublicationMutation = useUpdateAdPublicationMutation();
    const publicationQuery = useAdPublicationQuery(editingPublicationId);


    const initializedOptionsKeyRef = useRef<string | null>(null);

    const categoriesQuery = useQuery({
        queryKey: ["product-categories"],
        queryFn: getProductCategories,
        staleTime: 5 * 60 * 1000,
    });

    const watchedOptionCategoryId = Form.useWatch(
        "option_category_id",
        editForm,
    );

    const effectiveOptionCategoryId = (
        watchedOptionCategoryId
        ?? editingAd?.item.option_category_id
        ?? null
    );

    const selectedOptionCategory = (
        categoriesQuery.data ?? []
    ).find(
        (category) => category.id === effectiveOptionCategoryId,
    );

    const optionCategoryName = (
        selectedOptionCategory?.name
        ?? (
            effectiveOptionCategoryId === editingAd?.item.option_category_id
                ? editingAd?.item.option_category
                : ""
        )
        ?? ""
    );

    const {
        data: productOptionsData,
        isFetching: productOptionsLoading,
        error: productOptionsError,
    } = useProductOptions(optionCategoryName);

    const productOptions = productOptionsData ?? EMPTY_PRODUCT_OPTIONS;

    const optionsInitializationKey = editingAd
        ? [
            editingAd.type,
            editingAd.item.id,
            effectiveOptionCategoryId ?? "empty",
        ].join(":")
        : null;

    const isEditDataReady = (
        !editingPublication
        || Boolean(publicationQuery.data)
    );


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
    const [addressFilter, setAddressFilter] = useState("");

    const [minViews, setMinViews] = useState<number | null>(null);
    const [minContacts, setMinContacts] = useState<number | null>(null);

    const [sortField, setSortField] = useState<AvitoAdsSortField>(
        DEFAULT_SORT_FIELD,
    );
    const [sortDirection, setSortDirection] = useState<SortDirection>(
        DEFAULT_SORT_DIRECTION,
    );
    const [statsPeriod, setStatsPeriod] = useState<
        [Dayjs, Dayjs]
    >(() => [
        DEFAULT_STATS_DATE_FROM,
        DEFAULT_STATS_DATE_TO,
    ]);

    const statsDateFrom = statsPeriod[0].format("YYYY-MM-DD");
    const statsDateTo = statsPeriod[1].format("YYYY-MM-DD");
    const isDefaultStatsPeriod = (
        statsDateFrom
        === DEFAULT_STATS_DATE_FROM.format("YYYY-MM-DD")
        && statsDateTo
        === DEFAULT_STATS_DATE_TO.format("YYYY-MM-DD")
    );

    const ordering = SORT_ORDERINGS[sortField][sortDirection];
    const [filtersDrawerOpen, setFiltersDrawerOpen] = useState(false);
    const [selectedAdItems, setSelectedAdItems] = useState<SelectedAdItem[]>([]);

    const [isExportPollingEnabled, setIsExportPollingEnabled] = useState(false);

    const projectsQuery = useAvitoProjectsQuery({
        refetchInterval: isExportPollingEnabled ? 3000 : false,
    });

    // /Users/artem/Desktop/avito/frontend/src/pages/avito/AvitoAdsPage.tsx
    const requestCsvExportMutation = useRequestAvitoCsvExportMutation();
    const downloadCsvMutation = useDownloadAvitoCsvMutation();
    const bulkLifecycleMutation = useBulkUpdateAvitoAdsLifecycleMutation();
    const importStatsMutation = useImportAvitoDailyStatsMutation();


    const selectedAvitoAccount = (projectsQuery.data ?? []).find(
        (account) => account.id === avitoAccountId,
    );

    const activeFiltersCount = useMemo(
        () =>
            [
                Boolean(entityType),
                Boolean(hasAvitoId),
                Boolean(hasErrors),
                Boolean(addressFilter.trim()),
                !isDefaultStatsPeriod,
                minViews !== null,
                minContacts !== null,
                sortField !== DEFAULT_SORT_FIELD
                || sortDirection !== DEFAULT_SORT_DIRECTION,
            ].filter(Boolean).length,
        [
            addressFilter,
            entityType,
            hasAvitoId,
            hasErrors,
            isDefaultStatsPeriod,
            minContacts,
            minViews,
            sortDirection,
            sortField,

        ],
    );

    const resetPage = useCallback(() => {
        setPage(1);
        setSelectedAdItems([]);
    }, []);

    const resetFilters = useCallback(() => {
        setEntityType("");
        setHasAvitoId("");
        setHasErrors("");
        setAddressFilter("");
        setMinViews(null);
        setMinContacts(null);
        setSortField(DEFAULT_SORT_FIELD);
        setSortDirection(DEFAULT_SORT_DIRECTION);
        setStatsPeriod([
            DEFAULT_STATS_DATE_FROM,
            DEFAULT_STATS_DATE_TO,
        ]);
        resetPage();
    }, [resetPage]);

    const isCsvExportInProgress =
        selectedAvitoAccount?.export_status === "queued" ||
        selectedAvitoAccount?.export_status === "exporting";

    const isCsvReady =
        selectedAvitoAccount?.export_status === "clean" &&
        Boolean(selectedAvitoAccount.export_file_path);

    useEffect(() => {
        initializedOptionsKeyRef.current = null;

        if (!editingAd) {
            editForm.resetFields();
            return;
        }

        if (editingAd.type === "ad_publication") {
            if (!publicationQuery.data) {
                editForm.resetFields();
                return;
            }

            const initialValues = buildPublicationEditInitialValues(
                editingAd.item,
                publicationQuery.data.overrides,
            );

            const effectiveBaseData = parseJsonObjectForInputs(
                initialValues.base_data_json,
            );

            editForm.setFieldsValue({
                ...initialValues,
                option_category_id:
                    editingAd.item.option_category_id ?? undefined,
                autoload_category:
                    getCreativeAutoloadCategory(effectiveBaseData),
                options: {},
            });

            return;
        }

        const listing = editingAd.item;

        editForm.setFieldsValue({
            option_category_id:
                listing.option_category_id ?? undefined,
            autoload_category:
                getCreativeAutoloadCategory(listing.base_data),
            options: {},

            title: listing.title ?? "",
            description: listing.description ?? "",
            address: listing.address ?? "",
            desired_status: listing.desired_status ?? "publish",
            management_status: listing.management_status ?? "managed",
            image_urls_text: stringifyImageUrlsForForm(listing.image_urls),
            base_data_json: stringifyJsonForForm(listing.base_data),
            option_data_json: stringifyJsonForForm(listing.option_data),
        });
    }, [
        editForm,
        editingAd,
        publicationQuery.data,
    ]);

    useEffect(() => {
        if (
            !editingAd
            || !isEditDataReady
            || !optionsInitializationKey
        ) {
            return;
        }

        if (
            optionCategoryName
            && productOptionsData === undefined
        ) {
            return;
        }

        if (
            initializedOptionsKeyRef.current
            === optionsInitializationKey
        ) {
            return;
        }

        const currentOptionData = parseJsonObjectForInputs(
            editForm.getFieldValue("option_data_json"),
        );

        editForm.setFieldValue(
            "options",
            buildOptionFormValues(
                currentOptionData,
                productOptions,
            ),
        );

        initializedOptionsKeyRef.current =
            optionsInitializationKey;
    }, [
        editForm,
        editingAd,
        isEditDataReady,
        optionCategoryName,
        optionsInitializationKey,
        productOptions,
        productOptionsData,
    ]);

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
            address: addressFilter.trim(),
            stats_date_from: statsDateFrom,
            stats_date_to: statsDateTo,
            min_views: minViews ?? undefined,
            min_contacts: minContacts ?? undefined,
            ordering,
        }),
        [
            addressFilter,
            entityType,
            hasAvitoId,
            hasErrors,
            minContacts,
            minViews,
            ordering,
            page,
            search,
            statsDateFrom,
            statsDateTo,
        ],
    );

    const adsQuery = useAvitoAccountAdsQuery(avitoAccountId, queryParams);

    const statsSync = adsQuery.data?.stats_sync;

    const isStatsSyncing =
        statsSync?.status === "queued"
        || statsSync?.status === "running";

    const handleRefreshStats = async () => {
        if (!avitoAccountId) {
            return;
        }

        await importStatsMutation.mutateAsync({
            avitoAccountId,
        });
    };

    const renderStats = useCallback(
        (item: AvitoAccountAd) => {
            const stats = item.stats;

            if (!stats || stats.status === "processing") {
                return (
                    <Text type="secondary">
                        Данные в обработке
                    </Text>
                );
            }

            if (stats.status === "error") {
                return (
                    <Tooltip title={statsSync?.error || "Ошибка загрузки"}>
                        <Tag color="error">Ошибка</Tag>
                    </Tooltip>
                );
            }

            if (stats.status === "unavailable") {
                return <Text type="secondary">—</Text>;
            }

            const views = stats.views ?? 0;
            const contacts = stats.contacts ?? 0;
            const favorites = stats.favorites ?? 0;
            const totalSpend = (
                stats.total_spend === null
                    ? "—"
                    : `${stats.total_spend} ₽`
            );
            const conversion = (
                stats.views_to_contacts_conversion === null
                    ? "—"
                    : `${stats.views_to_contacts_conversion}%`
            );

            return (
                <div
                    style={{
                        display: "flex",
                        flexDirection: "row",
                        gap: "8px 14px",
                    }}
                >
                    <Tooltip title="Просмотры">
                    <span
                        aria-label={`Просмотры: ${views}`}
                        style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 5,
                        }}
                    >
                        <EyeOutlined style={{color: "#1677ff"}}/>
                        <Text>{views}</Text>
                    </span>
                    </Tooltip>

                    <Tooltip title="Контакты">
                    <span
                        aria-label={`Контакты: ${contacts}`}
                        style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 5,
                        }}
                    >
                        <UserOutlined style={{color: "#52c41a"}}/>
                        <Text>{contacts}</Text>
                    </span>
                    </Tooltip>

                    <Tooltip title="Добавления в избранное">
                    <span
                        aria-label={`Добавления в избранное: ${favorites}`}
                        style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 5,
                        }}
                    >
                        <HeartOutlined style={{color: "#ff4d4f"}}/>
                        <Text>{favorites}</Text>
                    </span>
                    </Tooltip>

                    <Tooltip title="Все расходы, включая деньги и бонусы">
                    <span
                        aria-label={`Расходы: ${totalSpend}`}
                        style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 5,
                        }}
                    >
                        <WalletOutlined style={{color: "#fa8c16"}}/>
                        <Text>{totalSpend}</Text>
                    </span>
                    </Tooltip>

                    <Tooltip title="Конверсия просмотра в контакт">
                    <span
                        aria-label={`Конверсия: ${conversion}`}
                        style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 5,
                            marginLeft: "10px",
                            fontWeight: "bold"
                        }}
                    >
                        <Text>{conversion}</Text>
                    </span>
                    </Tooltip>
                </div>
            );
        },
        [statsSync?.error],
    );

    const selectedAdKeys = useMemo(
        () => selectedAdItems.map((item) => `${item.entity_type}-${item.id}`),
        [selectedAdItems],
    );

    const extendableSelectedCount = useMemo(
        () => selectedAdItems.filter((item) => item.canExtend).length,
        [selectedAdItems],
    );


    const rowSelection = useMemo<TableProps<AvitoAccountAd>["rowSelection"]>(
        () => ({
            selectedRowKeys: selectedAdKeys,
            onChange: (_, selectedRows) => {
                setSelectedAdItems(
                    selectedRows
                        .filter((item) => item.avito_account === avitoAccountId)
                        .map((item) => ({
                            entity_type: item.entity_type,
                            id: item.id,
                            canExtend: canExtendAd(item),
                        })),
                );
            },
            getCheckboxProps: (item) => ({
                disabled: item.avito_account !== avitoAccountId,
            }),
        }),
        [avitoAccountId, selectedAdKeys],
    );

    const getEditAction = useCallback((item: AvitoAccountAd) => {
        if (item.entity_type === "ad_publication" && item.publication) {
            return {
                disabled: false,
                tooltip: "Редактировать публикацию",
                onClick: () => setEditingAd({type: "ad_publication", item}),
            };
        }

        if (item.entity_type === "avito_listing" && item.source === "avito_excel") {
            return {
                disabled: false,
                tooltip: "Редактировать импортированное Avito-объявление",
                onClick: () => setEditingAd({type: "avito_listing", item}),
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
    }, [navigate]);


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
        if (updateListingMutation.isPending || updatePublicationMutation.isPending) {
            return;
        }

        setEditingAd(null);
    };

    const handleEditFormValuesChange = (
        changedValues: Partial<AdEditFormValues>,
    ) => {
        if ("option_category_id" in changedValues) {
            editForm.setFieldValue("options", {});
            initializedOptionsKeyRef.current = null;
        }
    };

    const handleSubmitEditListing = async () => {
        const values = await editForm.validateFields();

        let currentBaseData: JsonObject;
        let currentOptionData: JsonObject;

        try {
            currentBaseData = parseJsonObject(
                values.base_data_json,
                "base_data",
            );
            currentOptionData = parseJsonObject(
                values.option_data_json,
                "option_data",
            );
        } catch (error) {
            message.error(
                error instanceof Error
                    ? error.message
                    : "Некорректный JSON",
            );
            return;
        }

        const autoloadCategory = values.autoload_category.trim();

        const nextBaseData: JsonObject = {
            ...currentBaseData,
            Category: autoloadCategory,
        };

        const nextKnownOptionData = buildOptionData(
            values.options ?? {},
            productOptions,
        );

        if (editingPublication) {
            if (!editingPublicationId || !publicationQuery.data) {
                return;
            }

            const nextOptionData = mergeUnknownOptionData(
                currentOptionData,
                nextKnownOptionData,
                productOptions,
            );

            try {
                const payload = buildPublicationUpdateRequest(
                    editingPublication,
                    publicationQuery.data.overrides,
                    {
                        ...values,
                        base_data_json:
                            stringifyJsonForForm(nextBaseData),
                        option_data_json:
                            stringifyJsonForForm(nextOptionData),
                    },
                );

                updatePublicationMutation.mutate(
                    {
                        publicationId: editingPublicationId,
                        data: payload,
                    },
                    {
                        onSuccess: () => {
                            setEditingAd(null);
                        },
                    },
                );
            } catch (error) {
                message.error(
                    error instanceof Error
                        ? error.message
                        : "Некорректные данные публикации",
                );
            }

            return;
        }

        if (!editingListing) {
            return;
        }

        const optionCategoryChanged = (
            typeof values.option_category_id === "number"
            && editingListing.option_category_id
            !== values.option_category_id
        );

        const nextOptionData = optionCategoryChanged
            ? nextKnownOptionData
            : mergeUnknownOptionData(
                currentOptionData,
                nextKnownOptionData,
                productOptions,
            );

        const payload: UpdateAvitoListingRequest = {
            option_category_id: values.option_category_id,
            title: values.title,
            description: values.description,
            address: values.address,
            desired_status: values.desired_status,
            management_status: values.management_status,
            base_data: nextBaseData,
            option_data: nextOptionData,
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
                    setEditingAd(null);
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

    const handleBulkLifecycle = (action: AvitoAdLifecycleAction) => {
        if (!avitoAccountId || selectedAdItems.length === 0) {
            return;
        }

        const items = selectedAdItems
            .filter((item) => action !== "extend" || item.canExtend)
            .map(({entity_type, id}) => ({
                entity_type,
                id,
            }));

        if (items.length === 0) {
            return;
        }

        bulkLifecycleMutation.mutate(
            {
                avitoAccountId,
                items,
                action,
            },
            {
                onSuccess: () => {
                    setSelectedAdItems([]);
                },
            },
        );
    };


    const columns = useMemo<TableProps<AvitoAccountAd>["columns"]>
    (() => [
        {
            title: "Заголовок",
            dataIndex: "title",
            key: "title",
            width: 250,
            render: (value: string | null, item) => (
                <Space orientation="vertical" size={0}>
                    <Text strong>{value || "Без названия"}</Text>
                    {item.row_id ? (
                        <Text
                            type="secondary"
                            style={{fontSize: 9}}
                            copyable={{text: item.row_id}}
                        >
                            id: {item.row_id}
                        </Text>
                    ) : (
                        <Text type="secondary" style={{fontSize: 11}}>
                            id: не задан
                        </Text>
                    )}
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
            title: "Адрес",
            dataIndex: "address",
            key: "address",
            width: 180,
            ellipsis: true,
            render: (value: string | null) => (
                <Text
                    type={value ? undefined : "secondary"}
                    style={{fontSize: 13}}
                >
                    {value || "Не указан"}
                </Text>
            ),
        },
        {
            title: "Окончание",
            key: "date_end",
            width: 100,
            render: (_, item) => {
                const deadline = getDateDeadlinePresentation(
                    item.published_end,
                );

                return (
                    <Tooltip
                        title={
                            dateEndSourceLabel[item.date_end_source] ??
                            item.date_end_source
                        }
                    >
                        <Text style={{color: dateDeadlineColor[deadline.tone]}}>
                            {deadline.text}
                        </Text>
                    </Tooltip>
                );
            },
        },
        {
            title: "Статистика",
            key: "stats",
            width: 220,
            render: (_, item) => renderStats(item),
        },
        {
            title: "Тип",
            dataIndex: "entity_type",
            key: "entity_type",
            width: 90,
            render: (value: string) => (
                <Tag color={entityTypeColor[value] ?? "default"}>
                    {entityTypeLabel[value] ?? value}
                </Tag>
            ),
        },
        {
            title: "Статус",
            dataIndex: "status",
            key: "status",
            width: 80,
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
            width: 100,
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
            width: 110,
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
            title: "Источник",
            dataIndex: "source",
            key: "source",
            width: 110,
            render: (value: string) => <Tag>{value}</Tag>,
        },
        {
            title: "Avito ID",
            dataIndex: "avito_id",
            key: "avito_id",
            width: 110,
            render: (value: string | null) =>
                value ? <Text>{value}</Text> : <Tag>Нет</Tag>,
        },
        {
            title: "",
            key: "actions",
            width: 37,
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
            render: (_, item) => {
                const action = getEditAction(item);

                return (
                    <Tooltip title={action.tooltip}>
                        <Button
                            size="small"
                            icon={<EditOutlined/>}
                            disabled={action.disabled}
                            onClick={action.onClick}
                        />
                    </Tooltip>
                );
            },
        },
    ], [
        getEditAction,
        renderStats,
    ]);

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
            <Row gutter={[16, 12]} align="top">
                <Col xs={24} lg={16}>
                    <Space orientation="vertical" size={0} style={{width: "100%"}}>
                        <Space
                            align="center"
                            size={10}
                            wrap
                            style={{marginBottom: 10}}
                        >
                            <Title level={2} style={{margin: 0}}>
                                Все объявления
                            </Title>

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
                        </Space>

                        <Text type="secondary">
                            Единый список: реальные объявления Avito и публикации сервиса, которые еще не связаны с
                            Avito ID.
                        </Text>

                        {statsSync?.coverage_from && (
                            <Text type="secondary">
                                Статистика накоплена с {statsSync.coverage_from}
                            </Text>
                        )}

                        {statsSync?.status === "error" && (
                            <Text type="danger">
                                Ошибка обновления статистики: {statsSync.error}
                            </Text>
                        )}

                        {isStatsSyncing && statsSync?.last_successful_at && (
                            <Text type="secondary">
                                Выполняется обновление. Пока показаны последние сохранённые значения.
                            </Text>
                        )}

                        {selectedAvitoAccount?.export_error && (
                            <Text type="danger">
                                {selectedAvitoAccount.export_error}
                            </Text>
                        )}

                        {selectedAvitoAccount?.export_error && (
                            <Text type="danger">
                                {selectedAvitoAccount.export_error}
                            </Text>
                        )}
                    </Space>
                </Col>

                <Col xs={24} lg={8}>
                    <Space
                        wrap
                        style={{
                            width: "100%",
                            justifyContent: "flex-end",
                            paddingTop: 5
                        }}
                    >
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
                            icon={<ReloadOutlined/>}
                            disabled={!avitoAccountId || isStatsSyncing}
                            loading={importStatsMutation.isPending || isStatsSyncing}
                            onClick={handleRefreshStats}
                        >
                            {isStatsSyncing
                                ? "Статистика обновляется"
                                : "Обновить статистику"}
                        </Button>
                    </Space>
                </Col>
            </Row>

            <div
                style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    flexWrap: "wrap",
                    width: "100%",
                }}
            >

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

                <RangePicker
                    allowClear={false}
                    value={statsPeriod}
                    format="DD.MM.YYYY"
                    separator="—"
                    placeholder={[
                        "Период от",
                        "Период до",
                    ]}
                    style={{width: 260}}
                    disabledDate={(current) => (
                        current.isAfter(
                            DEFAULT_STATS_DATE_TO,
                            "day",
                        )
                    )}
                    onChange={(dates) => {
                        const dateFrom = dates?.[0];
                        const dateTo = dates?.[1];

                        if (!dateFrom || !dateTo) {
                            return;
                        }

                        setStatsPeriod([
                            dateFrom.startOf("day"),
                            dateTo.startOf("day"),
                        ]);
                        resetPage();
                    }}
                />


                {selectedAvitoAccount?.export_error && (
                    <Text type="danger">
                        {selectedAvitoAccount.export_error}
                    </Text>
                )}

                <AdLifecycleBulkActions
                    selectedCount={selectedAdItems.length}
                    extendableCount={extendableSelectedCount}
                    disabled={!avitoAccountId}
                    loading={bulkLifecycleMutation.isPending}
                    onAction={handleBulkLifecycle}
                    onClearSelection={() => setSelectedAdItems([])}
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
                loading={adsQuery.isLoading}
                tableLayout="fixed"
                scroll={{x: 2000}}
                rowHoverable={false}
                pagination={{
                    current: page,
                    pageSize,
                    total: adsQuery.data?.count ?? 0,
                    showSizeChanger: false,
                }}
                onChange={handleTableChange}
            />

            <Drawer
                title={editingPublication ? "Редактирование публикации" : "Редактирование Avito-объявления"}
                open={editingAd !== null}
                size={720}
                onClose={handleCloseEditListing}
                extra={
                    <Space>
                        <Button onClick={handleCloseEditListing}>
                            Отмена
                        </Button>
                        <Button
                            type="primary"
                            loading={updateListingMutation.isPending || updatePublicationMutation.isPending}
                            disabled={
                                editingPublication !== null &&
                                (!publicationQuery.data || publicationQuery.isError)
                            }
                            onClick={handleSubmitEditListing}
                        >
                            Сохранить
                        </Button>
                    </Space>
                }
            >
                {editingPublication && publicationQuery.isLoading ? (
                    <Spin/>
                ) : editingPublication && (publicationQuery.isError || !publicationQuery.data) ? (
                    <Alert
                        type="error"
                        message="Публикация не найдена"
                        description="Проверьте, что публикация существует и принадлежит текущему кабинету."
                        showIcon
                    />
                ) : (
                    <Form
                        form={editForm}
                        layout="vertical"
                        onValuesChange={handleEditFormValuesChange}
                        disabled={updateListingMutation.isPending || updatePublicationMutation.isPending}
                    >
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

                        <Row gutter={16}>
                            <Col xs={24} md={12}>
                                <Form.Item
                                    name="option_category_id"
                                    label="Категория для отбора опций"
                                    extra={
                                        editingPublication
                                            ? "Категория наследуется от общего креатива."
                                            : "Определяет набор доступных параметров объявления."
                                    }
                                >
                                    <Select
                                        showSearch
                                        optionFilterProp="label"
                                        loading={categoriesQuery.isLoading}
                                        disabled={Boolean(editingPublication)}
                                        placeholder="Выберите категорию"
                                        options={(categoriesQuery.data ?? []).map(
                                            (category) => ({
                                                value: category.id,
                                                label: category.name,
                                            }),
                                        )}
                                    />
                                </Form.Item>
                            </Col>

                            <Col xs={24} md={12}>
                                <Form.Item
                                    name="autoload_category"
                                    label="Категория для файла автозагрузки"
                                    rules={[
                                        {
                                            required: true,
                                            message: "Укажите категорию автозагрузки",
                                        },
                                    ]}
                                    extra={
                                        editingPublication
                                            ? "Категория наследуется от общего креатива."
                                            : "Будет записана в колонку Category."
                                    }
                                >
                                    <AutoComplete
                                        disabled={Boolean(editingPublication)}
                                        options={AVITO_AUTOLOAD_CATEGORY_OPTIONS}
                                        placeholder="Например: Ремонт и строительство"
                                        filterOption={(inputValue, option) =>
                                            String(option?.value ?? "")
                                                .toLowerCase()
                                                .includes(inputValue.toLowerCase())
                                        }
                                    />
                                </Form.Item>
                            </Col>
                        </Row>

                        {editingPublication ? (
                            <Form.Item
                                name="status"
                                label="Статус"
                                rules={[{required: true, message: "Выберите статус"}]}
                            >
                                <Select
                                    options={[
                                        {value: "draft", label: "draft"},
                                        {value: "active", label: "active"},
                                        {value: "paused", label: "paused"},
                                        {value: "archived", label: "archived"},
                                        {value: "error", label: "error"},
                                    ]}
                                />
                            </Form.Item>
                        ) : (
                            <>
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
                            </>
                        )}

                        <Form.Item name="image_urls_text" label="Ссылки на фото">
                            <Input.TextArea rows={4}/>
                        </Form.Item>

                        <Form.Item name="base_data_json" hidden>
                            <Input.TextArea/>
                        </Form.Item>

                        <Form.Item name="option_data_json" hidden>
                            <Input.TextArea/>
                        </Form.Item>

                        <JsonObjectInputs
                            form={editForm}
                            name="base_data_json"
                            title="Базовые поля"
                            emptyText="Нет дополнительных базовых полей"
                            excludedKeys={[
                                "Category",
                                "DateEnd",
                                "date_end",
                            ]}
                        />

                        <Space
                            direction="vertical"
                            size={12}
                            style={{width: "100%", marginTop: 20}}
                        >
                            <Text strong style={{fontSize: 18}}>Опции категории</Text>

                            {productOptionsError && (
                                <Alert
                                    type="error"
                                    showIcon
                                    message="Не удалось загрузить опции"
                                    description={productOptionsError.message}
                                />
                            )}

                            {productOptionsLoading ? (
                                <Spin size="small"/>
                            ) : !optionCategoryName ? (
                                <Text type="secondary">
                                    Выберите категорию для отбора опций.
                                </Text>
                            ) : productOptions.length === 0 ? (
                                <Text type="secondary">
                                    Для категории «{optionCategoryName}» нет дополнительных опций.
                                </Text>
                            ) : (
                                <Row gutter={[16, 12]}>
                                    {productOptions.map((option) => {
                                        const allowMultiple = (
                                            option.allow_multiple
                                            ?? option.allow_multiple_options
                                        );

                                        const label = (
                                            option.option_title
                                            || option.option_title_ru
                                            || option.option_title_en
                                        );

                                        return (
                                            <Col key={option.id} xs={24} md={12}>
                                                <Form.Item
                                                    name={[
                                                        "options",
                                                        String(option.id),
                                                    ]}
                                                    label={label}
                                                    style={{marginBottom: 0}}
                                                >
                                                    {allowMultiple ? (
                                                        <Select
                                                            mode="tags"
                                                            allowClear
                                                            tokenSeparators={[","]}
                                                            placeholder={`Введите ${label}`}
                                                        />
                                                    ) : (
                                                        <Input
                                                            placeholder={`Введите ${label}`}
                                                        />
                                                    )}
                                                </Form.Item>
                                            </Col>
                                        );
                                    })}
                                </Row>
                            )}
                        </Space>

                    </Form>
                )}
            </Drawer>

            <Drawer
                title="Фильтры"
                open={filtersDrawerOpen}
                size={360}
                onClose={() => setFiltersDrawerOpen(false)}
                extra={
                    <Button onClick={resetFilters} disabled={activeFiltersCount === 0}>
                        Сбросить
                    </Button>
                }
            >
                <Space direction="vertical" size={16} style={{width: "100%"}}>
                    <Select
                        style={{width: "100%"}}
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
                        style={{width: "100%"}}
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
                        style={{width: "100%"}}
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

                    <Space
                        orientation="vertical"
                        size={4}
                        style={{width: "100%"}}
                    >
                        <Text strong>
                            Сортировка
                        </Text>

                        <Row gutter={8}>
                            <Col span={12}>
                                <Select<AvitoAdsSortField>
                                    value={sortField}
                                    style={{width: "100%"}}
                                    options={[
                                        {
                                            label: "Дата окончания",
                                            value: "date_end",
                                        },
                                        {
                                            label: "Просмотры",
                                            value: "views",
                                        },
                                        {
                                            label: "Контакты",
                                            value: "contacts",
                                        },
                                        {
                                            label: "Конверсия",
                                            value: "views_to_contacts_conversion",
                                        },
                                    ]}
                                    onChange={(value) => {
                                        setSortField(value);
                                        resetPage();
                                    }}
                                />
                            </Col>

                            <Col span={12}>

                                <Select<SortDirection>
                                    value={sortDirection}
                                    style={{width: "100%"}}
                                    options={[
                                        {
                                            label: "По возрастанию",
                                            value: "asc",
                                        },
                                        {
                                            label: "По убыванию",
                                            value: "desc",
                                        },
                                    ]}
                                    onChange={(value) => {
                                        setSortDirection(value);
                                        resetPage();
                                    }}
                                />
                            </Col>
                        </Row>

                    </Space>

                    <Space
                        orientation="vertical"
                        size={8}
                        style={{width: "100%"}}
                    >
                        <Text strong>
                            Статистика
                        </Text>

                        <Row gutter={8}>
                            <Col span={12}>
                                <Space
                                    orientation="vertical"
                                    size={4}
                                    style={{width: "100%"}}
                                >
                                    <Text type="secondary">
                                        Минимум просмотров
                                    </Text>

                                    <InputNumber<number>
                                        min={0}
                                        precision={0}
                                        controls={false}
                                        addonBefore="≥"
                                        placeholder="0"
                                        value={minViews}
                                        style={{width: "100%"}}
                                        onChange={(value) => {
                                            setMinViews(value);
                                            resetPage();
                                        }}
                                    />
                                </Space>
                            </Col>

                            <Col span={12}>
                                <Space
                                    orientation="vertical"
                                    size={4}
                                    style={{width: "100%"}}
                                >
                                    <Text type="secondary">
                                        Минимум контактов
                                    </Text>

                                    <InputNumber<number>
                                        min={0}
                                        precision={0}
                                        controls={false}
                                        addonBefore="≥"
                                        placeholder="0"
                                        value={minContacts}
                                        style={{width: "100%"}}
                                        onChange={(value) => {
                                            setMinContacts(value);
                                            resetPage();
                                        }}
                                    />
                                </Space>
                            </Col>
                        </Row>

                    </Space>

                    <Input
                        allowClear
                        prefix={<SearchOutlined/>}
                        placeholder="Адрес"
                        value={addressFilter}
                        onChange={(event) => {
                            setAddressFilter(event.target.value);
                            resetPage();
                        }}
                    />
                </Space>
            </Drawer>
        </Space>
    );
};
