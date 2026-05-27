import {useQuery} from "@tanstack/react-query";
import {avitoKeys, getAvitoListings} from "../../../shared/api/avito";
import {requireWorkspaceId} from "../../../shared/api/workspaceHeaders";
import {useCurrentWorkspace} from "../../workspace/model/useCurrentWorkspace";
import type {AvitoListingsQueryParams} from "../../../entities/avito/types";

export const useAvitoListingsQuery = (params: AvitoListingsQueryParams) => {
    const {currentWorkspaceId} = useCurrentWorkspace();

    return useQuery({
        queryKey: [
            ...avitoKeys.listings(currentWorkspaceId),
            params.page ?? 1,
            params.page_size ?? 50,
            params.avito_account_id ?? null,
            params.status ?? null,
            params.search ?? "",
            params.source ?? null,
            params.management_status ?? null,
            params.desired_status ?? null,
            params.has_unmapped ?? null,
        ],
        queryFn: () =>
            getAvitoListings(requireWorkspaceId(currentWorkspaceId), params),
        enabled: currentWorkspaceId !== null,
    })
}