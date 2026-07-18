import {useMutation, useQueryClient} from "@tanstack/react-query";
import {message} from "antd";
import {
    avitoKeys,
    bulkUpdateAvitoAdsLifecycle,
    bulkUpdateAvitoListingManagementStatus,
} from "../../../shared/api/avito";
import {getApiErrorMessage} from "../../../shared/api/errors";
import {requireWorkspaceId} from "../../../shared/api/workspaceHeaders";
import type {
    AvitoAdLifecycleAction,
    AvitoAdEntityType,
    AvitoListingManagementStatus,
} from "../../../entities/avito/types";
import {useCurrentWorkspace} from "../../workspace/model/useCurrentWorkspace";

interface BulkLifecycleVariables {
    avitoAccountId: number;
    items: Array<{
        entity_type: AvitoAdEntityType;
        id: number;
    }>;
    action: AvitoAdLifecycleAction;
}

interface BulkManagementStatusVariables {
    avitoAccountId: number;
    listingIds: number[];
    managementStatus: AvitoListingManagementStatus;
}

export const useBulkUpdateAvitoAdsLifecycleMutation = () => {
    const queryClient = useQueryClient();
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useMutation({
        mutationFn: ({avitoAccountId, items, action}: BulkLifecycleVariables) =>
            bulkUpdateAvitoAdsLifecycle({
                workspaceId: requireWorkspaceId(currentWorkspaceId),
                avitoAccountId,
                payload: {
                    action,
                    items,
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
                    queryKey: avitoKeys.publications(currentWorkspaceId),
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

            const skipped =
                result.publications.missing +
                result.listings.missing +
                result.listings.unsupported;

            if (result.action === "extend") {
                if (skipped > 0) {
                    message.warning(
                        `Продлено: ${result.updated}. Пропущено: ${skipped}.`,
                    );
                    return;
                }

                message.success(`Продлено объявлений: ${result.updated}`);
                return;
            }

            message.success(`Обновлено объявлений: ${result.updated}`);
        },
        onError: (error, variables) => {
            const fallbackMessage =
                variables.action === "extend"
                    ? "Не удалось продлить объявления"
                    : "Не удалось изменить трансляцию объявлений";

            message.error(getApiErrorMessage(error, fallbackMessage));
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