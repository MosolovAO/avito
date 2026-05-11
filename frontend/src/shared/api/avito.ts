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
    AvitoListingsQueryParams, AvitoListing,
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

export const importAvitoListings = async ({
                                              workspaceId,
                                              avitoAccountId
                                          }: AvitoAccountRequest
): Promise<AvitoQueuedTaskResponse> => {
    const response = await api.post<AvitoQueuedTaskResponse>(
        `/api/avito/accounts/${avitoAccountId}/import-listings/`,
        undefined,
        {
            headers: getWorkspaceHeaders(workspaceId)
        }
    )

    return response.data
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