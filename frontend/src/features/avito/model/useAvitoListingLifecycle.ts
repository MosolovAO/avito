import {useQuery} from "@tanstack/react-query";
import {
    avitoKeys,
    getAvitoListingLifecycleReport,
} from "../../../shared/api/avito";
import {requireWorkspaceId} from "../../../shared/api/workspaceHeaders";
import {useCurrentWorkspace} from "../../workspace/model/useCurrentWorkspace";

export const useAvitoListingLifecycleReportQuery = (
    avitoAccountId: number | undefined,
    soonDays = 3,
) => {
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useQuery({
        queryKey: avitoAccountId
            ? [...avitoKeys.lifecycle(currentWorkspaceId, avitoAccountId), soonDays]
            : [...avitoKeys.all, "lifecycle", currentWorkspaceId, null, soonDays],
        queryFn: () => {
            if (!avitoAccountId) {
                throw new Error("Avito-аккаунт не выбран");
            }

            return getAvitoListingLifecycleReport({
                workspaceId: requireWorkspaceId(currentWorkspaceId),
                avitoAccountId,
                soonDays,
            });
        },
        enabled: currentWorkspaceId !== null && avitoAccountId !== undefined,
    });
};