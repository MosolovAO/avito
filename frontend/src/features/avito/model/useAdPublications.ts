import {useQuery, useMutation, useQueryClient} from "@tanstack/react-query";
import {message} from "antd";
import {getApiErrorMessage} from "../../../shared/api/errors";
import {
    avitoKeys,
    getAdPublication,
    getAdPublications,
    updateAdPublication,
} from "../../../shared/api/avito";
import {requireWorkspaceId} from "../../../shared/api/workspaceHeaders";
import {useCurrentWorkspace} from "../../workspace/model/useCurrentWorkspace";
import type {AdPublicationsQueryParams, UpdateAdPublicationRequest} from "../../../entities/avito/types";


interface UpdateAdPublicationVariables {
    publicationId: number;
    data: UpdateAdPublicationRequest;
}

export const useAdPublicationsQuery = (
    params: AdPublicationsQueryParams,
) => {
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useQuery({
        queryKey: [
            ...avitoKeys.publications(currentWorkspaceId),
            params.page ?? 1,
            params.page_size ?? 50,
            params.avito_account ?? null,
            params.status ?? null,
            params.source ?? null,
            params.batch ?? null,
            params.search ?? ""
        ],
        queryFn: () =>
            getAdPublications(requireWorkspaceId(currentWorkspaceId), params),
        enabled: currentWorkspaceId !== null,
    })
}

export const useUpdateAdPublicationMutation = () => {
    const queryClient = useQueryClient();
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useMutation({
        mutationFn: ({publicationId, data}: UpdateAdPublicationVariables) =>
            updateAdPublication(
                requireWorkspaceId(currentWorkspaceId),
                publicationId,
                data,
            ),
        onSuccess: async () => {
            await Promise.all([
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.publications(currentWorkspaceId),
                }),
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.accounts(currentWorkspaceId),
                }),
            ]);

            message.success("Публикация обновлена, CSV помечен к пересборке");
        },
        onError: (error) => {
            message.error(
                getApiErrorMessage(error, "Не удалось обновить публикацию"),
            );
        },
    });
};

export const useAdPublicationQuery = (publicationId: number | null) => {
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useQuery({
        queryKey:
            publicationId === null
                ? [...avitoKeys.publications(currentWorkspaceId), "detail", null]
                : [...avitoKeys.publications(currentWorkspaceId), "detail", publicationId],
        queryFn: () =>
            getAdPublication(
                requireWorkspaceId(currentWorkspaceId),
                publicationId as number,
            ),
        enabled: currentWorkspaceId !== null && publicationId !== null,
    });
};