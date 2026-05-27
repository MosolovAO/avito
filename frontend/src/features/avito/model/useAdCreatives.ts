import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {message} from "antd";
import {
    avitoKeys,
    deleteAdCreative,
    getAdCreative,
    getAdCreatives,
    updateAdCreative,
} from "../../../shared/api/avito";
import {getApiErrorMessage} from "../../../shared/api/errors";
import {requireWorkspaceId} from "../../../shared/api/workspaceHeaders";
import {useCurrentWorkspace} from "../../workspace/model/useCurrentWorkspace";
import type {
    AdCreativesQueryParams,
    UpdateAdCreativeRequest,
} from "../../../entities/avito/types";

interface UpdateAdCreativeVariables {
    creativeId: number;
    data: UpdateAdCreativeRequest
}

export const useAdCreativesQuery = (params: AdCreativesQueryParams) => {
    const {currentWorkspaceId} = useCurrentWorkspace()

    return useQuery({
        queryKey: [
            ...avitoKeys.creatives(currentWorkspaceId),
            params.page ?? 1,
            params.page_size ?? 50,
            params.source ?? null,
            params.task ?? null,
            params.batch ?? null,
            params.search ?? "",
        ],
        queryFn: () =>
            getAdCreatives(requireWorkspaceId(currentWorkspaceId), params),
        enabled: currentWorkspaceId !== null
    })
}

export const useAdCreativeQuery = (creativeId: number | null) => {
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useQuery({
        queryKey:
            creativeId === null
                ? [...avitoKeys.creatives(currentWorkspaceId), "detail", null]
                : [...avitoKeys.creatives(currentWorkspaceId), "detail", creativeId],
        queryFn: () =>
            getAdCreative(requireWorkspaceId(currentWorkspaceId), creativeId as number),
        enabled: currentWorkspaceId !== null && creativeId !== null
    })
}

export const useUpdateAdCreativeMutation = () => {
    const queryClient = useQueryClient()
    const {currentWorkspaceId} = useCurrentWorkspace()

    return useMutation({
        mutationFn: ({creativeId, data}: UpdateAdCreativeVariables) =>
            updateAdCreative(
                requireWorkspaceId(currentWorkspaceId),
                creativeId,
                data
            ),
        onSuccess: async (_, variables) => {
            await Promise.all([
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.creatives(currentWorkspaceId),
                }),
                queryClient.invalidateQueries({
                    queryKey: [
                        ...avitoKeys.creatives(currentWorkspaceId),
                        "detail",
                        variables.creativeId,
                    ],
                }),
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.publications(currentWorkspaceId),
                }),
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.accounts(currentWorkspaceId),
                }),
            ]);

            message.success("Креатив обновлен, CSV помечен к пересборке");
        },
        onError: (error) => {
            message.error(
                getApiErrorMessage(error, "Не удалось обновить креатив")
            )
        }
    })
}

// src/features/avito/model/useAdCreatives.ts
export const useDeleteAdCreativeMutation = () => {
    const queryClient = useQueryClient();
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useMutation({
        mutationFn: (creativeId: number) =>
            deleteAdCreative(requireWorkspaceId(currentWorkspaceId), creativeId),
        onSuccess: async () => {
            await Promise.all([
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.creatives(currentWorkspaceId),
                }),
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.publications(currentWorkspaceId),
                }),
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.accounts(currentWorkspaceId),
                }),
            ]);

            message.success("Креатив удален, CSV поставлен в очередь на пересборку");
        },
        onError: (error) => {
            message.error(
                getApiErrorMessage(error, "Не удалось удалить креатив")
            );
        },
    });
};