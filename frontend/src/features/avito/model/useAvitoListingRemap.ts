import {useMutation, useQueryClient} from "@tanstack/react-query";
import {message} from "antd";
import {
    avitoKeys,
    remapAvitoListingImportFields,
} from "../../../shared/api/avito";
import {getApiErrorMessage} from "../../../shared/api/errors";
import {requireWorkspaceId} from "../../../shared/api/workspaceHeaders";
import {useCurrentWorkspace} from "../../workspace/model/useCurrentWorkspace";

interface RemapAvitoListingImportFieldsVariables {
    avitoAccountId: number;
}

export const useRemapAvitoListingImportFieldsMutation = () => {
    const queryClient = useQueryClient();
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useMutation({
        mutationFn: ({avitoAccountId}: RemapAvitoListingImportFieldsVariables) =>
            remapAvitoListingImportFields({
                workspaceId: requireWorkspaceId(currentWorkspaceId),
                avitoAccountId,
            }),
        onSuccess: async (result, variables) => {
            await Promise.all([
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.listings(currentWorkspaceId),
                }),
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.unmappedSummary(
                        currentWorkspaceId,
                        variables.avitoAccountId,
                    ),
                }),
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.accounts(currentWorkspaceId),
                }),
            ]);

            message.success(
                `Маппинг пересобран: обновлено ${result.updated}, осталось с unmapped ${result.still_with_unmapped}`,
            );
        },
        onError: (error) => {
            message.error(
                getApiErrorMessage(error, "Не удалось пересобрать маппинг"),
            );
        },
    });
};