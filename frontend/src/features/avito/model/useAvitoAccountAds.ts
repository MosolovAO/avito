import {useQuery} from "@tanstack/react-query";
import {
    avitoKeys,
    getAvitoAccountAds,
} from "../../../shared/api/avito";
import {requireWorkspaceId} from "../../../shared/api/workspaceHeaders";
import {useCurrentWorkspace} from "../../workspace/model/useCurrentWorkspace";
import type {AvitoAccountAdsQueryParams} from "../../../entities/avito/types";

export const useAvitoAccountAdsQuery = (
    avitoAccountId: number | null,
    params: AvitoAccountAdsQueryParams,
) => {
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useQuery({
        queryKey: [
            ...avitoKeys.ads(currentWorkspaceId, avitoAccountId),
            params.page ?? 1,
            params.page_size ?? 50,
            params.entity_type ?? "",
            params.source ?? "",
            params.status ?? "",
            params.desired_status ?? "",
            params.management_status ?? "",
            params.has_avito_id ?? "",
            params.has_errors ?? "",
            params.search ?? "",
        ],
        queryFn: () =>
            getAvitoAccountAds({
                workspaceId: requireWorkspaceId(currentWorkspaceId),
                avitoAccountId: avitoAccountId as number,
                params,
            }),
        enabled: currentWorkspaceId !== null && avitoAccountId !== null,
    });
};