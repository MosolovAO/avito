// src/entities/avito/types.ts
export type JsonObject = Record<string, unknown>;

export type AvitoExportStatus = "clean" | "dirty" | "queued" | "exporting" | "error";
export type AvitoListingSource = "api" | "avito_excel" | "service";
export type AvitoListingManagementStatus = "observed" | "managed" | "out_of_sync";
export type AvitoListingDesiredStatus = "publish" | "pause" | "archive";
export type AvitoAdEntityType = "avito_listing" | "ad_publication";
export type AvitoAdLifecycleAction = "publish" | "pause" | "delete" | "extend";

export interface AvitoAccount {
    id: number;
    name: string;
    external_account_id: string | null;
    client_id: string;
    has_client_secret: boolean;
    connection_status: AvitoConnectionStatus;
    connection_error: string | null;
    last_verified_at: string | null;
    is_active: boolean;
    feed_url: string | null;
    export_status: AvitoExportStatus;
    export_file_path: string | null;
    export_requested_at: string | null;
    export_started_at: string | null;
    last_exported_at: string | null;
    export_error: string | null;
    created_at: string;
    updated_at: string;
    sync_status: AvitoSyncStatus;
    sync_requested_at: string | null;
    sync_started_at: string | null;
    last_synced_at: string | null;
    sync_error: string | null;
    last_sync_total_received: number;
    last_sync_created_listings: number;
    last_sync_updated_listings: number;
}

export interface ProductSchedule {
    frequency: 1 | 2 | 3 | 4
    days: Array<string | null>
}

export interface AdCreativeProject {
    id: number;
    name: string;
}

export type ProductImageValue = File | ProductImageAssetValue | string


export interface ProductImageAssetValue {
    id: number
    url: string
}

export interface AvitoListingsQueryParams {
    page?: number;
    page_size?: number;
    avito_account_id?: number;
    status?: string;
    search?: string;
    source?: AvitoListingSource;
    management_status?: AvitoListingManagementStatus;
    desired_status?: AvitoListingDesiredStatus;
    has_unmapped?: boolean;
}

export type AvitoSyncStatus = "idle" | "queued" | "syncing" | "error";

export interface ConnectAvitoAccountResponse {
    status: "connected";
    avito_account_id: number;
    external_account_id: string | null;
}

export interface AvitoOAuthStartResponse {
    authorization_url: string;
}

export interface AvitoOAuthCallbackParams {
    code?: string;
    state?: string;
    error?: string;
    error_description?: string;
}

export interface AvitoOAuthCallbackResponse {
    status: "connected";
    avito_account_id: number;
    external_account_id: string | null;
}

export interface AvitoQueuedTaskResponse {
    status: "queued";
    task_id: string;
    avito_account_id: number;
}

export interface LinkAvitoPublicationsRequest {
    row_ids?: string[];
}

export interface ImportAvitoDailyStatsRequest {
    date_from: string;
    date_to: string;
    listing_ids?: number[];
}

export type AdPublicationStatus =
    | "draft"
    | "active"
    | "paused"
    | "archived"
    | "error";

export interface AvitoListing {
    id: number;
    avito_account: number;
    avito_account_name: string;
    publication: number | null;
    publication_row_id: string | null;
    date_end: string;
    date_end_source: "avito" | "none";

    source: AvitoListingSource;
    management_status: AvitoListingManagementStatus;
    desired_status: AvitoListingDesiredStatus;

    avito_id: string;
    row_id: string | null;
    status: string | null;
    title: string | null;
    description: string;
    address: string;
    url: string | null;

    sheet_name: string;
    category_path: string;
    option_category_id: number | null;
    option_category: string | null;
    image_urls: string[];
    base_data: JsonObject;
    option_data: JsonObject;
    unmapped_data: JsonObject;

    published_at: string | null;
    last_seen_at: string | null;
    created_at: string;
    updated_at: string;
}

export interface AvitoAccountAdAutoloadError {
    message?: unknown;
    raw?: JsonObject;
    status?: string;
}

export interface AvitoAccountAd {
    entity_type: AvitoAdEntityType;
    id: number;
    avito_account: number;
    avito_account_name: string;
    publication: number | null;
    publication_row_id: string | null;
    option_category_id: number | null;
    option_category: string | null;

    date_end: string;
    date_end_source: "avito" | "publication" | "creative" | "default" | "none";

    source: AvitoListingSource | AdPublicationSource;
    status: string | null;
    desired_status: AvitoListingDesiredStatus | null;
    management_status: AvitoListingManagementStatus | null;

    row_id: string | null;
    avito_id: string | null;
    title: string | null;
    description: string;
    address: string;
    url: string | null;

    image_urls: string[];
    base_data: JsonObject;
    option_data: JsonObject;
    unmapped_data: JsonObject;

    has_publication: boolean;
    has_avito_id: boolean;
    has_errors: boolean;
    autoload_error: AvitoAccountAdAutoloadError | null;

    published_at: string | null;
    last_seen_at: string | null;
    created_at: string;
    updated_at: string;
}

export interface AvitoAccountAdsQueryParams {
    page?: number;
    page_size?: number;
    entity_type?: "" | AvitoAdEntityType;
    source?: string;
    status?: string;
    desired_status?: AvitoListingDesiredStatus | "";
    management_status?: AvitoListingManagementStatus | "";
    has_avito_id?: "" | "1" | "0";
    has_errors?: "" | "1" | "0";
    search?: string;
    address?: string;
    ordering?: "" | "date_end" | "-date_end";
}

export interface AvitoAccountAdsResponse {
    count: number;
    page: number;
    page_size: number;
    results: AvitoAccountAd[];
}


export interface BulkAvitoAdLifecycleItem {
    entity_type: AvitoAdEntityType;
    id: number;
}

export interface BulkAvitoAdLifecycleRequest {
    action: AvitoAdLifecycleAction;
    items: BulkAvitoAdLifecycleItem[];
}

export interface BulkAvitoAdLifecycleResponse {
    action: AvitoAdLifecycleAction;
    requested: number;
    updated: number;
    publications: {
        requested: number;
        matched: number;
        updated: number;
        missing: number;
    };
    listings: {
        requested: number;
        matched: number;
        updated: number;
        missing: number;
        unsupported: number;
        redirected_to_publications: number;
    };
}

export interface AvitoExcelPreviewRow {
    sheet_name: string;
    category_path: string;
    row_number: number;
    row_id: string | null;
    avito_id: string | null;
    title: string | null;
    status: string | null;
    mapped_data: JsonObject;
    unmapped_data: JsonObject;
    errors: string[];
}

export interface AvitoExcelImportPreviewResponse {
    total_sheets: number;
    total_rows: number;
    rows_with_errors: number;
    categories: string[];
    unmapped_columns: string[];
    rows: AvitoExcelPreviewRow[];
}

export interface AvitoExcelImportApplyResponse {
    total_rows: number;
    skipped_rows: number;
    created_listings: number;
    updated_listings: number;
    rows_with_errors: number;
    unmapped_columns: string[];
}

export interface BulkAvitoListingManagementStatusRequest {
    listing_ids: number[];
    management_status: AvitoListingManagementStatus;
}

export interface BulkAvitoListingStatusResponse {
    requested: number;
    matched: number;
    updated: number;
    missing: number;
    management_status?: AvitoListingManagementStatus;
}

export interface AvitoListingLifecycleItem {
    listing_id: number;
    avito_id: string;
    row_id: string | null;
    title: string;
    status: string;
    desired_status: AvitoListingDesiredStatus;
    date_end: string | null;
    days_left: number | null;
    action: string;
}

export interface AvitoListingLifecycleReport {
    total_checked: number;
    expired: number;
    expires_soon: number;
    active_ok: number;
    items: AvitoListingLifecycleItem[];
}

export interface AvitoListingDailyStats {
    id: number;
    listing: number;
    date: string;
    views: number;
    contacts: number;
    favorites: number;
    calls: number;
    messages: number;
    raw_metrics: JsonObject;
    created_at: string;
    updated_at: string;
}

export interface CreateAvitoAccountRequest {
    name: string;
    client_id?: string;
    client_secret?: string;
    is_active?: boolean;
}


export interface UpdateAvitoAccountRequest {
    name?: string;
    client_id?: string;
    client_secret?: string;
    is_active?: boolean;
}

export type AvitoConnectionStatus =
    | "not_configured"
    | "not_connected"
    | "connected"
    | "error";

export interface VerifyAvitoConnectionResponse {
    status: AvitoConnectionStatus;
    detail?: string;
    external_account_id: string | null;
    last_verified_at: string | null;
}

export type AdPublicationSource = "auto" | "manual";

export interface AdPublication {
    id: number;
    avito_account: number;
    avito_account_name: string;
    creative: number;
    creative_title: string;
    task: number | null;
    batch: number | null;
    source: AdPublicationSource;
    status: AdPublicationStatus;
    row_id: string | null;
    address: string;
    overrides: JsonObject;
    avito_listing_id: number | null;
    avito_id: string | null;
    avito_listing_url: string | null;
    published_at: string | null;
    last_exported_at: string | null;
    archived_at: string | null;
    created_at: string;
    updated_at: string;
    effective_date_end: string;
    date_end_source: "publication" | "creative" | "default";
}

export interface AdPublicationsQueryParams {
    page?: number;
    page_size?: number;
    avito_account?: number;
    status?: AdPublicationStatus;
    source?: AdPublicationSource;
    search?: string;
    batch?: number;
}

export interface RequestAvitoCsvExportResponse {
    status: "queued";
    task_id: string;
    avito_account_id: number;
    export_status: AvitoExportStatus;
}

export type AdBatchSource = "auto" | "manual" | "import";
export type AdBatchStatus = "draft" | "completed" | "failed";

export interface AdBatch {
    id: number;
    task: number | null;
    task_name: string | null;
    source: AdBatchSource;
    status: AdBatchStatus;
    created_by: number | null;
    created_by_email: string | null;
    total_creatives: number;
    total_publications: number;
    error_message: string | null;
    created_at: string;
    completed_at: string | null;
}

export interface AdBatchesQueryParams {
    page?: number;
    page_size?: number;
    source?: AdBatchSource;
    status?: AdBatchStatus;
}

export type AdCreativeSource = "auto" | "manual";

export interface AdCreativeEdit {
    id: number;
    option_category_id: number | null;
    option_category: string | null;
    title: string;
    description: string;
    image_urls: string[];
    base_data: JsonObject;
    option_data: JsonObject;
    updated_at: string;
}
export interface AdCreative {
    id: number;
    task: number | null;
    task_name: string | null;
    batch: number | null;
    batch_source: AdBatchSource | null;
    source: AdCreativeSource;
    option_category_id: number | null;
    option_category: string | null;
    title: string;
    description: string;
    image_urls: string[];
    base_data: JsonObject;
    option_data: JsonObject;
    identity_hash: string | null;
    publications_count: number;
    projects: AdCreativeProject[];
    created_at: string;
    updated_at: string;
    effective_date_end: string;
    date_end_source: "creative" | "default";
}

export interface UpdateAdCreativeRequest {
    option_category_id?: number;
    title?: string;
    description?: string;
    image_urls?: string[];
    base_data?: JsonObject;
    option_data?: JsonObject;
    clear_publication_override_fields?: string[];
    expected_updated_at?: string;
}

export interface AdCreativesQueryParams {
    page?: number;
    page_size?: number;
    source?: AdCreativeSource;
    task?: number;
    batch?: number;
    search?: string;
    avito_account?: number;
}

export interface AdCreativesQueryParams {
    page?: number;
    page_size?: number;
    source?: AdCreativeSource;
    task?: number;
    batch?: number;
    search?: string;
}

export interface UpdateAdPublicationRequest {
    address?: string;
    status?: AdPublicationStatus;
    overrides?: JsonObject;
}

export interface CreateManualMassPostingRequest {
    option_category_id: number;
    avito_account_ids: number[];
    addresses: string[];
    title: string;
    description: string;
    image_urls?: string[];
    base_data?: JsonObject;
    option_data?: JsonObject;
}
export interface ManualMassPostingResponse {
    batch: {
        id: number;
        source: AdBatchSource;
        status: AdBatchStatus;
        total_creatives: number;
        total_publications: number;
    };
    creative: {
        id: number;
        title: string;
    };
    publications: Array<{
        id: number;
        row_id: string | null;
        avito_account_id: number;
        address: string;
        status: AdPublicationStatus;
    }>;
}

export interface UpdateAvitoListingRequest {
    title?: string;
    description?: string;
    address?: string;
    status?: string;
    image_urls?: string[];
    desired_status?: AvitoListingDesiredStatus;
    management_status?: AvitoListingManagementStatus;
    base_data?: JsonObject;
    option_data?: JsonObject;
    option_category_id?: number;
}

export interface AvitoListingUnmappedColumnSummary {
    name: string;
    count: number;
}

export interface AvitoListingUnmappedSummary {
    total_listings_with_unmapped: number;
    total_columns: number;
    columns: AvitoListingUnmappedColumnSummary[];
}

export interface AvitoListingRemapImportFieldsResponse {
    total_checked: number;
    updated: number;
    skipped_without_raw_data: number;
    still_with_unmapped: number;
    resolved_columns: string[];
}