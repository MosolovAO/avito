import {useMutation, useQueryClient} from "@tanstack/react-query";
import {message} from "antd";
import {
    avitoKeys,
    importAvitoDailyStats,
    importAvitoListings,
    linkAvitoPublications,
    connectAvitoAccountByCredentials
} from "../../../shared/api/avito";
import {getApiErrorMessage} from "../../../shared/api/errors";
import {requireWorkspaceId} from "../../../shared/api/workspaceHeaders";
import {useCurrentWorkspace} from "../../workspace/model/useCurrentWorkspace";
import type {
    ImportAvitoDailyStatsRequest,
} from "../../../entities/avito/types";

import {
    verifyAvitoConnection,
} from "../../../shared/api/avito";

interface AvitoAccountActionVariables {
    avitoAccountId: number;
}

interface LinkAvitoPublicationsVariables extends AvitoAccountActionVariables {
    rowIds?: string[];
}

interface ImportAvitoDailyStatsVariables extends AvitoAccountActionVariables {
    payload: ImportAvitoDailyStatsRequest;
}


export const useImportAvitoListingsMutation = () => {
    const queryClient = useQueryClient();
    const {currentWorkspaceId} = useCurrentWorkspace()

    return useMutation({
        mutationFn: async ({avitoAccountId}: AvitoAccountActionVariables) => {
            const workspaceId = requireWorkspaceId(currentWorkspaceId)

            return importAvitoListings({
                    workspaceId,
                    avitoAccountId
                }
            )
        },
        onSuccess: async () => {
            await Promise.all([
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.accounts(currentWorkspaceId),
                }),
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.listings(currentWorkspaceId),
                }),
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.publications(currentWorkspaceId),
                }),
            ]);

            message.success("Импорт объявлений поставлен в очередь")
        },
        onError: (error) => {
            message.error(
                getApiErrorMessage(error, "Не удалось запустить импорт объявлений")
            )
        }
    })
}

export const useLinkAvitoPublicationsMutation = () => {
    const queryClient = useQueryClient();
    const {currentWorkspaceId} = useCurrentWorkspace()

    return useMutation({
        mutationFn: async ({
                               avitoAccountId,
                               rowIds
                           }: LinkAvitoPublicationsVariables) => {
            const workspaceId = requireWorkspaceId(currentWorkspaceId);

            return linkAvitoPublications({
                workspaceId,
                avitoAccountId,
                rowIds,
            })
        },
        onSuccess: async () => {
            await Promise.all([
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.listings(currentWorkspaceId),
                }),
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.publications(currentWorkspaceId),
                }),
            ]);

            message.success("Связка публикаций с Avito ID поставлена в очередь")
        },
        onError: (error) => {
            message.error(
                getApiErrorMessage(error, "Не удалось связать публикации с Avito ID"),
            )
        }
    })
}

export const useImportAvitoDailyStatsMutation = () => {
    const queryClient = useQueryClient();
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useMutation({
        mutationFn: async ({
                               avitoAccountId,
                               payload
                           }: ImportAvitoDailyStatsVariables) => {
            const workspaceId = requireWorkspaceId(currentWorkspaceId);

            return importAvitoDailyStats({
                workspaceId,
                avitoAccountId,
                payload
            })
        },
        onSuccess: async () => {
            await queryClient.invalidateQueries({
                queryKey: avitoKeys.stats(currentWorkspaceId),
            });

            message.success("Импорт статистики поставлен в очередь")
        },
        onError: (error) => {
            message.error(
                getApiErrorMessage(error, "Не удалось запустить импорт статистики")
            )
        }
    })
}

export const useVerifyAvitoConnectionMutation = () => {
    const queryClient = useQueryClient();
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useMutation({
        mutationFn: async ({avitoAccountId}: AvitoAccountActionVariables) => {
            const workspaceId = requireWorkspaceId(currentWorkspaceId);

            return verifyAvitoConnection({
                workspaceId,
                avitoAccountId,
            });
        },
        onSuccess: async () => {
            await queryClient.invalidateQueries({
                queryKey: avitoKeys.accounts(currentWorkspaceId),
            });

            message.success("Подключение Avito работает");
        },
        onError: (error) => {
            message.error(
                getApiErrorMessage(error, "Не удалось проверить подключение Avito"),
            );
        },
    });
};

export const useConnectAvitoAccountMutation = () => {
    const queryClient = useQueryClient();
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useMutation({
        mutationFn: async ({avitoAccountId}: AvitoAccountActionVariables) => {
            const workspaceId = requireWorkspaceId(currentWorkspaceId);

            return connectAvitoAccountByCredentials({
                workspaceId,
                avitoAccountId,
            });
        },
        onSuccess: async () => {
            await queryClient.invalidateQueries({
                queryKey: avitoKeys.accounts(currentWorkspaceId),
            });

            message.success("Avito API подключен");
        },
        onError: (error) => {
            message.error(
                getApiErrorMessage(error, "Не удалось подключить Avito API"),
            );
        },
    });
};