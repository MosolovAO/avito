// src/features/avito/index.ts
export {
    useImportAvitoDailyStatsMutation,
    useLinkAvitoPublicationsMutation,
    useVerifyAvitoConnectionMutation,
} from "./model/useAvitoActions";

export {
    useAvitoProjectsQuery,
    useCreateAvitoProjectMutation,
    useDeleteAvitoProjectMutation,
    useUpdateAvitoProjectMutation,
} from "./model/useAvitoProjects";

export {useAvitoListingsQuery} from "./model/useAvitoListings";
export {
    useAdPublicationQuery,
    useAdPublicationsQuery,
    useUpdateAdPublicationMutation,
} from "./model/useAdPublications";

export {
    useDownloadAvitoCsvMutation,
    useRequestAvitoCsvExportMutation,
} from "./model/useAvitoCsv";

export {useAdBatchesQuery} from "./model/useAdBatches";

export {
    useAdCreativeQuery,
    useAdCreativesQuery,
    useDeleteAdCreativeMutation,
    useUpdateAdCreativeMutation,
} from "./model/useAdCreatives";

export {useCreateManualMassPostingMutation} from "./model/useManualMassPosting";

export {
    useApplyAvitoExcelImportMutation,
    usePreviewAvitoExcelImportMutation,
} from "./model/useAvitoExcelImport";

export {
    useBulkUpdateAvitoListingDesiredStatusMutation,
    useBulkUpdateAvitoListingManagementStatusMutation,
} from "./model/useAvitoListingBulkActions";

export {
    useAvitoListingLifecycleReportQuery,
} from "./model/useAvitoListingLifecycle";

export {
    useUpdateAvitoListingMutation,
} from "./model/useAvitoListingEditing";
export {
    useAvitoListingUnmappedSummaryQuery,
} from "./model/useAvitoListingUnmappedSummary";

export {
    useRemapAvitoListingImportFieldsMutation,
} from "./model/useAvitoListingRemap";

export {
    useAvitoAccountAdsQuery,
} from "./model/useAvitoAccountAds";