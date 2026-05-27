import {useQuery} from "@tanstack/react-query";
import {avitoKeys, getAdBatches} from "../../../shared/api/avito";
import {requireWorkspaceId} from "../../../shared/api/workspaceHeaders";
import {useCurrentWorkspace} from "../../workspace/model/useCurrentWorkspace";
import type {AdBatchesQueryParams} from "../../../entities/avito/types";

export const useAdBatchesQuery = (params: AdBatchesQueryParams) => {
    const {currentWorkspaceId} = useCurrentWorkspace()

    return useQuery({
        queryKey: [
            ...avitoKeys.batches(currentWorkspaceId),
            params.page ?? 1,
            params.page_size ?? 50,
            params.source ?? null,
            params.status ?? null,
        ],
        queryFn: () =>
            getAdBatches(requireWorkspaceId(currentWorkspaceId), params),
        enabled: currentWorkspaceId !== null
    })
}