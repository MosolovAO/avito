import {useMutation, useQueryClient} from "@tanstack/react-query";
import {message} from "antd";
import {
    avitoKeys,
    downloadAvitoCsv,
    requestAvitoCsvExport,
} from "../../../shared/api/avito";
import {getApiErrorMessage} from "../../../shared/api/errors";
import {requireWorkspaceId} from "../../../shared/api/workspaceHeaders";
import {useCurrentWorkspace} from "../../workspace/model/useCurrentWorkspace";

interface AvitoCsvVariables {
    avitoAccountId: number;
    fileName?: string
}

export const useRequestAvitoCsvExportMutation = () => {
    const queryClient = useQueryClient();
    const {currentWorkspaceId} = useCurrentWorkspace()

    return useMutation({
        mutationFn: async ({avitoAccountId}: AvitoCsvVariables) => {
            const workspaceId = requireWorkspaceId(currentWorkspaceId)

            return requestAvitoCsvExport({
                workspaceId,
                avitoAccountId
            })
        },
        onSuccess: async () => {
            await queryClient.invalidateQueries({
                queryKey: avitoKeys.accounts(currentWorkspaceId),
            });

            message.success("CSV-выгрузка поставлена в очередь")
        },
        onError: (error) => {
            message.error(
                getApiErrorMessage(error, "Не удалось запустить CSV-выгрузку")
            )
        }
    })
}

export const useDownloadAvitoCsvMutation = () => {
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useMutation({
        mutationFn: async ({avitoAccountId, fileName}: AvitoCsvVariables) => {
            const workspaceId = requireWorkspaceId(currentWorkspaceId);

            const blob = await downloadAvitoCsv({
                workspaceId,
                avitoAccountId
            })

            return {
                blob,
                fileName: fileName || `avito-account-${avitoAccountId}.csv`
            }
        },
        onSuccess: ({blob, fileName}) => {
            const url = URL.createObjectURL(blob);
            const anchor = document.createElement("a")

            anchor.href = url;
            anchor.download = fileName;
            anchor.click();

            URL.revokeObjectURL(url)
        },
        onError: (error) => {
            message.error(
                getApiErrorMessage(error, "Не удалось скачать CSV-файл")
            )
        }
    })
}