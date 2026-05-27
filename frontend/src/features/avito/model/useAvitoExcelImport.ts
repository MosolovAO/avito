import {useMutation, useQueryClient} from "@tanstack/react-query";
import {message} from "antd";
import {
    applyAvitoExcelImport,
    avitoKeys,
    previewAvitoExcelImport,
} from "../../../shared/api/avito";
import {getApiErrorMessage} from "../../../shared/api/errors";
import {requireWorkspaceId} from "../../../shared/api/workspaceHeaders";
import {useCurrentWorkspace} from "../../workspace/model/useCurrentWorkspace";

interface AvitoExcelImportVariables {
    avitoAccountId: number;
    file: File;
}

export const usePreviewAvitoExcelImportMutation = () => {
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useMutation({
        mutationFn: ({avitoAccountId, file}: AvitoExcelImportVariables) =>
            previewAvitoExcelImport({
                workspaceId: requireWorkspaceId(currentWorkspaceId),
                avitoAccountId,
                file,
            }),
        onError: (error) => {
            message.error(
                getApiErrorMessage(error, "Не удалось прочитать XLSX-файл"),
            );
        },
    });
};

export const useApplyAvitoExcelImportMutation = () => {
    const queryClient = useQueryClient();
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useMutation({
        mutationFn: ({avitoAccountId, file}: AvitoExcelImportVariables) =>
            applyAvitoExcelImport({
                workspaceId: requireWorkspaceId(currentWorkspaceId),
                avitoAccountId,
                file,
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
                    queryKey: avitoKeys.unmappedSummary(
                        currentWorkspaceId,
                        variables.avitoAccountId,
                    ),
                }),
            ]);

            message.success(
                `Импорт завершен: создано ${result.created_listings}, обновлено ${result.updated_listings}`,
            );
        },
        onError: (error) => {
            message.error(
                getApiErrorMessage(error, "Не удалось импортировать XLSX-файл"),
            );
        },
    });
};