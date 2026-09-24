import {
    useMutation,
    useQueryClient,
} from "@tanstack/react-query";
import type {QueryClient} from "@tanstack/react-query";

import {
    approveAutomationDecision,
    automationKeys,
    rejectAutomationDecision,
} from "../../../entities/automation";

interface DecisionMutationVariables {
    workspaceId: number;
    runId: number;
    decisionId: number;
}

const invalidateDecisionCache = async (
    queryClient: QueryClient,
    workspaceId: number,
    runId: number,
): Promise<void> => {
    await Promise.all([
        queryClient.invalidateQueries({
            queryKey: automationKeys.run(
                workspaceId,
                runId,
            ),
        }),
        queryClient.invalidateQueries({
            queryKey: automationKeys.decisionsRoot(
                workspaceId,
                runId,
            ),
        }),
        queryClient.invalidateQueries({
            queryKey:
                automationKeys.inboxSummary(workspaceId),
        }),
    ]);
};

export const useApproveAutomationDecisionMutation = () => {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: ({
                         workspaceId,
                         runId,
                         decisionId,
                     }: DecisionMutationVariables) => (
            approveAutomationDecision(
                workspaceId,
                runId,
                decisionId,
            )
        ),
        onSuccess: (
            _response,
            variables,
        ) => invalidateDecisionCache(
            queryClient,
            variables.workspaceId,
            variables.runId,
        ),
    });
};

export const useRejectAutomationDecisionMutation = () => {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: ({
                         workspaceId,
                         runId,
                         decisionId,
                     }: DecisionMutationVariables) => (
            rejectAutomationDecision(
                workspaceId,
                runId,
                decisionId,
            )
        ),
        onSuccess: (
            _response,
            variables,
        ) => invalidateDecisionCache(
            queryClient,
            variables.workspaceId,
            variables.runId,
        ),
    });
};