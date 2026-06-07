import {useMutation, useQueryClient} from "@tanstack/react-query";
import {message} from "antd";
import {
    avitoKeys,
    updateAvitoListing,
    extendAvitoListing
} from "../../../shared/api/avito";
import {getApiErrorMessage} from "../../../shared/api/errors";
import {requireWorkspaceId} from "../../../shared/api/workspaceHeaders";
import type {UpdateAvitoListingRequest} from "../../../entities/avito/types";
import {useCurrentWorkspace} from "../../workspace/model/useCurrentWorkspace";

interface UpdateAvitoListingVariables {
    listingId: number;
    avitoAccountId: number;
    data: UpdateAvitoListingRequest;
}

export const useUpdateAvitoListingMutation = () => {
    const queryClient = useQueryClient();
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useMutation({
        mutationFn: ({listingId, data}: UpdateAvitoListingVariables) =>
            updateAvitoListing(
                requireWorkspaceId(currentWorkspaceId),
                listingId,
                data,
            ),
        onSuccess: async (_, variables) => {
            await Promise.all([
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.listings(currentWorkspaceId),
                }),
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.lifecycle(
                        currentWorkspaceId,
                        variables.avitoAccountId,
                    ),
                }),
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.accounts(currentWorkspaceId),
                }),
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.unmappedSummary(
                        currentWorkspaceId,
                        variables.avitoAccountId,
                    ),
                }),
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.ads(
                        currentWorkspaceId,
                        variables.avitoAccountId,
                    ),
                }),
            ]);

            message.success("Объявление обновлено");
        },
        onError: (error) => {
            message.error(
                getApiErrorMessage(error, "Не удалось обновить объявление"),
            );
        },
    });
};

export const useExtendAvitoListingMutation = () => {
    const queryClient = useQueryClient();
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useMutation({
        mutationFn: ({listingId}: { listingId: number; avitoAccountId: number }) =>
            extendAvitoListing(requireWorkspaceId(currentWorkspaceId), listingId),
        onSuccess: async (_, variables) => {
            await Promise.all([
                queryClient.invalidateQueries({queryKey: avitoKeys.listings(currentWorkspaceId)}),
                queryClient.invalidateQueries({queryKey: avitoKeys.accounts(currentWorkspaceId)}),
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.lifecycle(currentWorkspaceId, variables.avitoAccountId),
                }),
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.ads(currentWorkspaceId, variables.avitoAccountId),
                }),
            ]);

            message.success("Объявление Avito продлено, CSV помечен к пересборке");
        },
        onError: (error) => {
            message.error(getApiErrorMessage(error, "Не удалось продлить объявление Avito"));
        },
    });
};