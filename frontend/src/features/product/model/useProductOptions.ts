import {useQuery} from '@tanstack/react-query'
import type {ProductOption} from '../../../entities/product'
import {getProductOptions} from '../../../shared/api/products'

const PRODUCT_OPTIONS_STALE_TIME_MS = 5 * 60 * 1000

export const productOptionsQueryKey = (category: string) =>
    ['product-options', category] as const

export const useProductOptions = (category: string) => {
    return useQuery<ProductOption[], Error>({
        queryKey: productOptionsQueryKey(category),
        queryFn: () => getProductOptions(category),
        enabled: category.length > 0,
        staleTime: PRODUCT_OPTIONS_STALE_TIME_MS,
    })
}