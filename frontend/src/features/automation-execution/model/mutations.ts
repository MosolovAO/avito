import {
    useMutation,
    useQueryClient,
} from "@tanstack/react-query";
import type {QueryClient} from "@tanstack/react-query";

import {
    archiveAutomation,
    automationKeys,
    createAutomation,
    createAutomationPreview,
    createAutomationRun,
    updateAutomation,
} from "../../../entities/automation";
import type {
    CreateAutomationRequest,
    UpdateAutomationRequest,
} from "../../../entities/automation";

interface CreateAutomationVariables {
    workspaceId: number;
    payload: CreateAutomationRequest;
}

interface UpdateAutomationVariables {
    workspaceId: number;
    automationId: number;
    payload: UpdateAutomationRequest;
}

interface CreateAutomationRunVariables {
    workspaceId: number;
    automationId: number;
    idempotencyKey: string;
}

interface ArchiveAutomationVariables {
    workspaceId: number;
    automationId: number;
}

const invalidateAutomationCache = async (
    queryClient: QueryClient,
    workspaceId: number,
    automationId: number,
): Promise<void> => {
    await Promise.all([
        queryClient.invalidateQueries({
            queryKey:
                automationKeys.listRoot(workspaceId),
        }),
        queryClient.invalidateQueries({
            queryKey:
                automationKeys.detail(
                    workspaceId,
                    automationId,
                ),
        }),
        queryClient.invalidateQueries({
            queryKey:
                automationKeys.runsRoot(
                    workspaceId,
                    automationId,
                ),
        }),
    ]);
};

export const useCreateAutomationMutation = () => {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: ({
                         workspaceId,
                         payload,
                     }: CreateAutomationVariables) => (
            createAutomation(workspaceId, payload)
        ),
        onSuccess: (
            createdAutomation,
            variables,
        ) => invalidateAutomationCache(
            queryClient,
            variables.workspaceId,
            createdAutomation.id,
        ),
    });
};

export const useUpdateAutomationMutation = () => {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: ({
                         workspaceId,
                         automationId,
                         payload,
                     }: UpdateAutomationVariables) => (
            updateAutomation(
                workspaceId,
                automationId,
                payload,
            )
        ),
        onSuccess: (
            updatedAutomation,
            variables,
        ) => invalidateAutomationCache(
            queryClient,
            variables.workspaceId,
            updatedAutomation.id,
        ),
    });
};

export const useCreateAutomationPreviewMutation = () => {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: ({
                         workspaceId,
                         automationId,
                         idempotencyKey,
                     }: CreateAutomationRunVariables) => (
            createAutomationPreview(
                workspaceId,
                automationId,
                idempotencyKey,
            )
        ),
        onSuccess: (
            _createdRun,
            variables,
        ) => {
            void invalidateAutomationCache(
                queryClient,
                variables.workspaceId,
                variables.automationId,
            );
        },
    });
};

export const useCreateAutomationRunMutation = () => {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: ({
                         workspaceId,
                         automationId,
                         idempotencyKey,
                     }: CreateAutomationRunVariables) => (
            createAutomationRun(
                workspaceId,
                automationId,
                idempotencyKey,
            )
        ),
        onSuccess: (
            _createdRun,
            variables,
        ) => invalidateAutomationCache(
            queryClient,
            variables.workspaceId,
            variables.automationId,
        ),
    });
};

export const useArchiveAutomationMutation = () => {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: ({
                         workspaceId,
                         automationId,
                     }: ArchiveAutomationVariables) => (
            archiveAutomation(
                workspaceId,
                automationId,
            )
        ),
        onSuccess: (
            _result,
            variables,
        ) => invalidateAutomationCache(
            queryClient,
            variables.workspaceId,
            variables.automationId,
        ),
    });
};