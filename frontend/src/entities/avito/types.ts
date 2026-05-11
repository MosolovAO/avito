// src/entities/avito/types.ts
export type JsonObject = Record<string, unknown>;

export type AvitoExportStatus = "clean" | "dirty" | "exporting" | "error";

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
}

export interface AvitoListingsQueryParams {
    page?: number;
    page_size?: number;
    avito_account?: number;
    status?: string;
    search?: string;
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
    publication: number | null;
    avito_id: string;
    status: string | null;
    title: string | null;
    url: string | null;
    imported_payload: JsonObject;
    published_at: string | null;
    last_seen_at: string | null;
    created_at: string;
    updated_at: string;
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