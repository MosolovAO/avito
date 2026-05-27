import {useMutation, useQueryClient} from "@tanstack/react-query";
import {message} from "antd";
import {
    avitoKeys,
    bulkUpdateAvitoListingDesiredStatus,
    bulkUpdateAvitoListingManagementStatus,
} from "../../../shared/api/avito";
import {getApiErrorMessage} from "../../../shared/api/errors";
import {requireWorkspaceId} from "../../../shared/api/workspaceHeaders";
import type {
    AvitoListingDesiredStatus,
    AvitoListingManagementStatus,
} from "../../../entities/avito/types";
import {useCurrentWorkspace} from "../../workspace/model/useCurrentWorkspace";

interface BulkDesiredStatusVariables {
    avitoAccountId: number;
    listingIds: number[];
    desiredStatus: AvitoListingDesiredStatus;
}

interface BulkManagementStatusVariables {
    avitoAccountId: number;
    listingIds: number[];
    managementStatus: AvitoListingManagementStatus;
}

export const useBulkUpdateAvitoListingDesiredStatusMutation = () => {
    const queryClient = useQueryClient();
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useMutation({
        mutationFn: ({avitoAccountId, listingIds, desiredStatus}: BulkDesiredStatusVariables) =>
            bulkUpdateAvitoListingDesiredStatus({
                workspaceId: requireWorkspaceId(currentWorkspaceId),
                avitoAccountId,
                payload: {
                    listing_ids: listingIds,
                    desired_status: desiredStatus,
                },
            }),
        onSuccess: async (result, variables) => {
            await Promise.all([
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.accounts(currentWorkspaceId),
                }),
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
                    queryKey: avitoKeys.ads(
                        currentWorkspaceId,
                        variables.avitoAccountId,
                    ),
                }),
            ]);

            message.success(`Обновлено объявлений: ${result.updated}`);
        },
        onError: (error) => {
            message.error(
                getApiErrorMessage(error, "Не удалось обновить желаемый статус"),
            );
        },
    });
};

export const useBulkUpdateAvitoListingManagementStatusMutation = () => {
    const queryClient = useQueryClient();
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useMutation({
        mutationFn: ({
                         avitoAccountId,
                         listingIds,
                         managementStatus,
                     }: BulkManagementStatusVariables) =>
            bulkUpdateAvitoListingManagementStatus({
                workspaceId: requireWorkspaceId(currentWorkspaceId),
                avitoAccountId,
                payload: {
                    listing_ids: listingIds,
                    management_status: managementStatus,
                },
            }),
        onSuccess: async (result, variables) => {
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
            ]);

            message.success(`Обновлено объявлений: ${result.updated}`);
        },
        onError: (error) => {
            message.error(
                getApiErrorMessage(error, "Не удалось обновить статус управления"),
            );
        },
    });
};