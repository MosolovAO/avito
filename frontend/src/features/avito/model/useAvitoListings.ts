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
            params.avito_account ?? null,
            params.status ?? null,
            params.search ?? "",
        ],
        queryFn: () =>
            getAvitoListings(requireWorkspaceId(currentWorkspaceId), params),
        enabled: currentWorkspaceId !== null,
    })
}