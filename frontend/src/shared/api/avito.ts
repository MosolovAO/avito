import api from "./axios";
import {getWorkspaceHeaders} from "./workspaceHeaders";
import type {
    AvitoAccount,
    AvitoQueuedTaskResponse,
    CreateAvitoAccountRequest,
    ImportAvitoDailyStatsRequest,
    LinkAvitoPublicationsRequest,
    UpdateAvitoAccountRequest,
    VerifyAvitoConnectionResponse,
    ConnectAvitoAccountResponse,
    AvitoListingsQueryParams,
    AvitoListing,
    AdPublication,
    AdPublicationsQueryParams,
    RequestAvitoCsvExportResponse,
    AdBatch,
    AdBatchesQueryParams,
    AdCreative,
    AdCreativeEdit,
    AdCreativesQueryParams,
    UpdateAdCreativeRequest,
    UpdateAdPublicationRequest,
    CreateManualMassPostingRequest,
    ManualMassPostingResponse,
    AvitoExcelImportApplyResponse,
    AvitoExcelImportPreviewResponse,
    AvitoListingLifecycleReport,
    BulkAvitoListingManagementStatusRequest,
    BulkAvitoListingStatusResponse,
    UpdateAvitoListingRequest,
    AvitoListingUnmappedSummary,
    AvitoListingRemapImportFieldsResponse,
    AvitoAccountAdsQueryParams,
    AvitoAccountAdsResponse,
    BulkAvitoAdLifecycleRequest,
    BulkAvitoAdLifecycleResponse,
} from "../../entities/avito/types";

import type {PaginatedResponse} from "./pagination";

interface WorkspaceScopedRequest {
    workspaceId: number;
}

interface AvitoAccountRequest extends WorkspaceScopedRequest {
    avitoAccountId: number;
}

export const avitoKeys = {
    all: ["avito"] as const,
    accounts: (workspaceId: number | null) =>
        [...avitoKeys.all, "accounts", workspaceId] as const,
    account: (workspaceId: number | null, avitoAccountId: number) =>
        [...avitoKeys.accounts(workspaceId), avitoAccountId] as const,
    listings: (workspaceId: number | null) =>
        [...avitoKeys.all, "listings", workspaceId] as const,
    publications: (workspaceId: number | null) =>
        [...avitoKeys.all, "publications", workspaceId] as const,
    stats: (workspaceId: number | null) =>
        [...avitoKeys.all, "stats", workspaceId] as const,
    batches: (workspaceId: number | null) =>
        [...avitoKeys.all, "batches", workspaceId] as const,
    creatives: (workspaceId: number | null) =>
        [...avitoKeys.all, "creatives", workspaceId] as const,
    excelPreview: (workspaceId: number | null, avitoAccountId: number) =>
        [...avitoKeys.account(workspaceId, avitoAccountId), "excel-preview"] as const,
    lifecycle: (workspaceId: number | null, avitoAccountId: number) =>
        [...avitoKeys.account(workspaceId, avitoAccountId), "lifecycle"] as const,
    unmappedSummary: (workspaceId: number | null, avitoAccountId: number) =>
        [...avitoKeys.account(workspaceId, avitoAccountId), "unmapped-summary"] as const,
    ads: (workspaceId: number | null, avitoAccountId: number | null) =>
        [...avitoKeys.all, "ads", workspaceId, avitoAccountId] as const,
};

export const getAvitoAccounts = async (
    workspaceId: number
): Promise<AvitoAccount[]> => {
    const response = await api.get<AvitoAccount[]>("/api/avito-accounts/", {
        headers: getWorkspaceHeaders(workspaceId)
    });

    return response.data;
}

export const getAvitoAccount = async (
    workspaceId: number,
    avitoAccountId: number,
): Promise<AvitoAccount> => {
    const response = await api.get<AvitoAccount>(
        `/api/avito-accounts/${avitoAccountId}/`,
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const createAvitoAccount = async (
    workspaceId: number,
    data: CreateAvitoAccountRequest
): Promise<AvitoAccount> => {
    const response = await api.post<AvitoAccount>("/api/avito-accounts/", data, {
        headers: getWorkspaceHeaders(workspaceId)
    });

    return response.data
}

export const updateAvitoAccount = async (
    workspaceId: number,
    avitoAccountId: number,
    data: UpdateAvitoAccountRequest,
): Promise<AvitoAccount> => {
    const response = await api.patch<AvitoAccount>(
        `/api/avito-accounts/${avitoAccountId}/`,
        data,
        {
            headers: getWorkspaceHeaders(workspaceId)
        }
    );
    return response.data;
}

export const deleteAvitoAccount = async (
    workspaceId: number,
    avitoAccountId: number,
): Promise<void> => {
    await api.delete(`/api/avito-accounts/${avitoAccountId}/`, {
        headers: getWorkspaceHeaders(workspaceId)
    })
}


export const linkAvitoPublications = async ({
                                                workspaceId,
                                                avitoAccountId,
                                                rowIds,
                                            }: AvitoAccountRequest & {
    rowIds?: string[];
}): Promise<AvitoQueuedTaskResponse> => {
    const payload: LinkAvitoPublicationsRequest = rowIds && rowIds.length > 0 ? {row_ids: rowIds} : {};
    const response = await api.post<AvitoQueuedTaskResponse>(
        `/api/avito/accounts/${avitoAccountId}/link-publications/`,
        payload,
        {
            headers: getWorkspaceHeaders(workspaceId)
        }
    )
    return response.data
}


export const importAvitoDailyStats = async ({
                                                workspaceId,
                                                avitoAccountId,
                                                payload
                                            }: AvitoAccountRequest & {
    payload: ImportAvitoDailyStatsRequest;
}): Promise<AvitoQueuedTaskResponse> => {
    const response = await api.post<AvitoQueuedTaskResponse>(
        `/api/avito/accounts/${avitoAccountId}/import-daily-stats/`,
        payload,
        {
            headers: getWorkspaceHeaders((workspaceId))
        }
    )

    return response.data
}

export const verifyAvitoConnection = async ({
                                                workspaceId,
                                                avitoAccountId,
                                            }: AvitoAccountRequest): Promise<VerifyAvitoConnectionResponse> => {
    const response = await api.post<VerifyAvitoConnectionResponse>(
        `/api/avito/accounts/${avitoAccountId}/verify-connection/`,
        undefined,
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const connectAvitoAccountByCredentials = async ({
                                                           workspaceId,
                                                           avitoAccountId,
                                                       }: AvitoAccountRequest): Promise<ConnectAvitoAccountResponse> => {
    const response = await api.post<ConnectAvitoAccountResponse>(
        `/api/avito/accounts/${avitoAccountId}/connect-by-credentials/`,
        undefined,
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const getAvitoListings = async (
    workspaceId: number,
    params: AvitoListingsQueryParams = {}
): Promise<PaginatedResponse<AvitoListing>> => {
    const response = await api.get<PaginatedResponse<AvitoListing>>(
        "/api/avito-listings/",
        {
            params,
            headers: getWorkspaceHeaders(workspaceId)
        }
    )

    return response.data
}

export const getAvitoAccountAds = async ({
                                             workspaceId,
                                             avitoAccountId,
                                             params = {},
                                         }: AvitoAccountRequest & {
    params?: AvitoAccountAdsQueryParams;
}): Promise<AvitoAccountAdsResponse> => {
    const response = await api.get<AvitoAccountAdsResponse>(
        `/api/avito/accounts/${avitoAccountId}/ads/`,
        {
            params,
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const getAdPublications = async (
    workspaceId: number,
    params: AdPublicationsQueryParams = {},
): Promise<PaginatedResponse<AdPublication>> => {
    const response = await api.get<PaginatedResponse<AdPublication>>(
        "/api/ad-publications/",
        {
            params,
            headers: getWorkspaceHeaders(workspaceId)
        }
    );

    return response.data
}

export const requestAvitoCsvExport = async ({
                                                workspaceId,
                                                avitoAccountId,
                                            }: AvitoAccountRequest): Promise<RequestAvitoCsvExportResponse> => {
    const response = await api.post<RequestAvitoCsvExportResponse>(
        `/api/avito/accounts/${avitoAccountId}/csv/export/`,
        undefined,
        {
            headers: getWorkspaceHeaders(workspaceId)
        }
    )

    return response.data
}

export const downloadAvitoCsv = async ({
                                           workspaceId,
                                           avitoAccountId
                                       }: AvitoAccountRequest): Promise<Blob> => {
    const response = await api.get<Blob>(
        `/api/avito/accounts/${avitoAccountId}/csv/download/`,
        {
            responseType: "blob",
            headers: getWorkspaceHeaders(workspaceId)
        }
    );

    return response.data
}
export const getAdBatches = async (
    workspaceId: number,
    params: AdBatchesQueryParams = {},
): Promise<PaginatedResponse<AdBatch>> => {
    const response = await api.get<PaginatedResponse<AdBatch>>(
        "/api/ad-batches/",
        {
            params,
            headers: getWorkspaceHeaders(workspaceId)
        }
    )

    return response.data
}

export const getAdCreatives = async (
    workspaceId: number,
    params: AdCreativesQueryParams = {}
): Promise<PaginatedResponse<AdCreative>> => {
    const response = await api.get<PaginatedResponse<AdCreative>>(
        "/api/ad-creatives/",
        {
            params,
            headers: getWorkspaceHeaders(workspaceId)
        }
    )

    return response.data
}

export const getAdCreative = async (
    workspaceId: number,
    creativeId: number,
): Promise<AdCreativeEdit> => {
    const response = await api.get<AdCreativeEdit>(
        `/api/ad-creatives/${creativeId}/`,
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const updateAdCreative = async (
    workspaceId: number,
    creativeId: number,
    data: UpdateAdCreativeRequest,
): Promise<AdCreative> => {
    const response = await api.patch<AdCreative>(
        `/api/ad-creatives/${creativeId}/`,
        data,
        {
            headers: getWorkspaceHeaders(workspaceId)
        }
    );

    return response.data
}

export const extendAdCreativePublications = async (
    workspaceId: number,
    creativeId: number,
): Promise<AdCreative> => {
    const response = await api.patch<AdCreative>(
        `/api/ad-creatives/${creativeId}/extend-publications/`,
        undefined,
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const deleteAdCreative = async (
    workspaceId: number,
    creativeId: number,
): Promise<void> => {
    await api.delete(
        `/api/ad-creatives/${creativeId}/`,
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );
};

export const updateAdPublication = async (
    workspaceId: number,
    publicationId: number,
    data: UpdateAdPublicationRequest,
): Promise<AdPublication> => {
    const response = await api.patch<AdPublication>(
        `/api/ad-publications/${publicationId}/`,
        data,
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const extendAdPublication = async (
    workspaceId: number,
    publicationId: number,
): Promise<AdPublication> => {
    const response = await api.patch<AdPublication>(
        `/api/ad-publications/${publicationId}/extend/`,
        undefined,
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const inheritAdPublicationCreativeDateEnd = async (
    workspaceId: number,
    publicationId: number,
): Promise<AdPublication> => {
    const response = await api.patch<AdPublication>(
        `/api/ad-publications/${publicationId}/inherit-creative-date-end/`,
        undefined,
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};
export const getAdPublication = async (
    workspaceId: number,
    publicationId: number,
): Promise<AdPublication> => {
    const response = await api.get<AdPublication>(
        `/api/ad-publications/${publicationId}/`,
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const createManualMassPosting = async (
    workspaceId: number,
    data: CreateManualMassPostingRequest,
): Promise<ManualMassPostingResponse> => {
    const response = await api.post<ManualMassPostingResponse>(
        "/api/manual-mass-posting/",
        data,
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const previewAvitoExcelImport = async ({
                                                  workspaceId,
                                                  avitoAccountId,
                                                  file,
                                              }: AvitoAccountRequest & {
    file: File;
}): Promise<AvitoExcelImportPreviewResponse> => {
    const formData = new FormData();
    formData.append("file", file, file.name);

    const response = await api.post<AvitoExcelImportPreviewResponse>(
        `/api/avito/accounts/${avitoAccountId}/excel-import/preview/`,
        formData,
        {
            headers: {
                ...getWorkspaceHeaders(workspaceId),
                "Content-Type": "multipart/form-data",
            },
        },
    );

    return response.data;
};

export const applyAvitoExcelImport = async ({
                                                workspaceId,
                                                avitoAccountId,
                                                file,
                                            }: AvitoAccountRequest & {
    file: File;
}): Promise<AvitoExcelImportApplyResponse> => {
    const formData = new FormData();
    formData.append("file", file, file.name);

    const response = await api.post<AvitoExcelImportApplyResponse>(
        `/api/avito/accounts/${avitoAccountId}/excel-import/apply/`,
        formData,
        {
            headers: {
                ...getWorkspaceHeaders(workspaceId),
                "Content-Type": "multipart/form-data",
            },
        },
    );

    return response.data;
};

export const bulkUpdateAvitoAdsLifecycle = async ({
                                                      workspaceId,
                                                      avitoAccountId,
                                                      payload,
                                                  }: AvitoAccountRequest & {
    payload: BulkAvitoAdLifecycleRequest;
}): Promise<BulkAvitoAdLifecycleResponse> => {
    const response = await api.post<BulkAvitoAdLifecycleResponse>(
        `/api/avito/accounts/${avitoAccountId}/ads/bulk-lifecycle/`,
        payload,
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const bulkUpdateAvitoListingManagementStatus = async ({
                                                                 workspaceId,
                                                                 avitoAccountId,
                                                                 payload,
                                                             }: AvitoAccountRequest & {
    payload: BulkAvitoListingManagementStatusRequest;
}): Promise<BulkAvitoListingStatusResponse> => {
    const response = await api.post<BulkAvitoListingStatusResponse>(
        `/api/avito/accounts/${avitoAccountId}/listings/bulk-management-status/`,
        payload,
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const getAvitoListingLifecycleReport = async ({
                                                         workspaceId,
                                                         avitoAccountId,
                                                         soonDays = 3,
                                                     }: AvitoAccountRequest & {
    soonDays?: number;
}): Promise<AvitoListingLifecycleReport> => {
    const response = await api.get<AvitoListingLifecycleReport>(
        `/api/avito/accounts/${avitoAccountId}/listings/lifecycle-report/`,
        {
            params: {soon_days: soonDays},
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const getAvitoListingUnmappedSummary = async ({
                                                         workspaceId,
                                                         avitoAccountId,
                                                         limit = 100,
                                                     }: AvitoAccountRequest & {
    limit?: number;
}): Promise<AvitoListingUnmappedSummary> => {
    const response = await api.get<AvitoListingUnmappedSummary>(
        `/api/avito/accounts/${avitoAccountId}/listings/unmapped-summary/`,
        {
            params: {limit},
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const remapAvitoListingImportFields = async ({
                                                        workspaceId,
                                                        avitoAccountId,
                                                    }: AvitoAccountRequest): Promise<AvitoListingRemapImportFieldsResponse> => {
    const response = await api.post<AvitoListingRemapImportFieldsResponse>(
        `/api/avito/accounts/${avitoAccountId}/listings/remap-import-fields/`,
        undefined,
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const updateAvitoListing = async (
    workspaceId: number,
    listingId: number,
    data: UpdateAvitoListingRequest,
): Promise<AvitoListing> => {
    const response = await api.patch<AvitoListing>(
        `/api/avito-listings/${listingId}/`,
        data,
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const extendAvitoListing = async (
    workspaceId: number,
    listingId: number,
): Promise<AvitoListing> => {
    const response = await api.patch<AvitoListing>(
        `/api/avito-listings/${listingId}/extend/`,
        undefined,
        {headers: getWorkspaceHeaders(workspaceId)},
    );

    return response.data;
};