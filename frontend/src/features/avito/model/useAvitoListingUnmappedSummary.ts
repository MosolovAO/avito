import {useQuery} from "@tanstack/react-query";
import {
    avitoKeys,
    getAvitoListingUnmappedSummary,
} from "../../../shared/api/avito";
import {requireWorkspaceId} from "../../../shared/api/workspaceHeaders";
import {useCurrentWorkspace} from "../../workspace/model/useCurrentWorkspace";

export const useAvitoListingUnmappedSummaryQuery = (
    avitoAccountId: number | undefined,
    limit = 100,
) => {
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useQuery({
        queryKey: avitoAccountId
            ? [...avitoKeys.unmappedSummary(currentWorkspaceId, avitoAccountId), limit]
            : [...avitoKeys.all, "unmapped-summary", currentWorkspaceId, null, limit],
        queryFn: () => {
            if (!avitoAccountId) {
                throw new Error("Avito-аккаунт не выбран");
            }

            return getAvitoListingUnmappedSummary({
                workspaceId: requireWorkspaceId(currentWorkspaceId),
                avitoAccountId,
                limit,
            });
        },
        enabled: currentWorkspaceId !== null && avitoAccountId !== undefined,
    });
};