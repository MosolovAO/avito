// src/features/avito/model/useManualMassPosting.ts
import {useMutation, useQueryClient} from "@tanstack/react-query";
import {message} from "antd";
import {
    avitoKeys,
    createManualMassPosting,
} from "../../../shared/api/avito";
import {getApiErrorMessage} from "../../../shared/api/errors";
import {requireWorkspaceId} from "../../../shared/api/workspaceHeaders";
import {useCurrentWorkspace} from "../../workspace/model/useCurrentWorkspace";
import type {CreateManualMassPostingRequest} from "../../../entities/avito/types";

export const useCreateManualMassPostingMutation = () => {
    const queryClient = useQueryClient();
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useMutation({
        mutationFn: (data: CreateManualMassPostingRequest) =>
            createManualMassPosting(
                requireWorkspaceId(currentWorkspaceId),
                data,
            ),
        onSuccess: async (data) => {
            await Promise.all([
                queryClient.invalidateQueries({
                    queryKey: avitoKeys.batches(currentWorkspaceId),
                }),
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

            message.success(
                `Создано публикаций: ${data.batch.total_publications}`,
            );
        },
        onError: (error) => {
            message.error(
                getApiErrorMessage(error, "Не удалось создать ручной масс-постинг"),
            );
        },
    });
};
