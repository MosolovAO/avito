// src/features/avito/model/useAvitoProjects.ts
import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {message} from "antd";
import {
    avitoKeys,
    createAvitoAccount,
    deleteAvitoAccount,
    getAvitoAccounts,
    updateAvitoAccount,
} from "../../../shared/api/avito";
import {getApiErrorMessage} from "../../../shared/api/errors";
import {requireWorkspaceId} from "../../../shared/api/workspaceHeaders";
import {useCurrentWorkspace} from "../../workspace/model/useCurrentWorkspace";
import type {
    CreateAvitoAccountRequest,
    UpdateAvitoAccountRequest,
} from "../../../entities/avito/types";

interface UpdateAvitoAccountVariables {
    avitoAccountId: number;
    data: UpdateAvitoAccountRequest;
}

export const useAvitoProjectsQuery = (options?: { refetchInterval?: number | false }) => {
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useQuery({
        queryKey: avitoKeys.accounts(currentWorkspaceId),
        queryFn: () => getAvitoAccounts(requireWorkspaceId(currentWorkspaceId)),
        enabled: currentWorkspaceId !== null,
        refetchInterval: options?.refetchInterval,
    });
};

export const useCreateAvitoProjectMutation = () => {
    const queryClient = useQueryClient();
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useMutation({
        mutationFn: (data: CreateAvitoAccountRequest) =>
            createAvitoAccount(requireWorkspaceId(currentWorkspaceId), data),
        onSuccess: async () => {
            await queryClient.invalidateQueries({
                queryKey: avitoKeys.accounts(currentWorkspaceId),
            });

            message.success("Проект создан");
        },
        onError: (error) => {
            message.error(getApiErrorMessage(error, "Не удалось создать проект"));
        },
    });
};

export const useUpdateAvitoProjectMutation = () => {
    const queryClient = useQueryClient();
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useMutation({
        mutationFn: ({avitoAccountId, data}: UpdateAvitoAccountVariables) =>
            updateAvitoAccount(
                requireWorkspaceId(currentWorkspaceId),
                avitoAccountId,
                data,
            ),
        onSuccess: async () => {
            await queryClient.invalidateQueries({
                queryKey: avitoKeys.accounts(currentWorkspaceId),
            });

            message.success("Проект обновлен");
        },
        onError: (error) => {
            message.error(getApiErrorMessage(error, "Не удалось обновить проект"));
        },
    });
};

export const useDeleteAvitoProjectMutation = () => {
    const queryClient = useQueryClient();
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useMutation({
        mutationFn: (avitoAccountId: number) =>
            deleteAvitoAccount(requireWorkspaceId(currentWorkspaceId), avitoAccountId),
        onSuccess: async () => {
            await queryClient.invalidateQueries({
                queryKey: avitoKeys.accounts(currentWorkspaceId),
            });

            message.success("Проект удален");
        },
        onError: (error) => {
            message.error(getApiErrorMessage(error, "Не удалось удалить проект"));
        },
    });
};
