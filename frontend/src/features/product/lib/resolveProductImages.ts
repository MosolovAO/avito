import type {ProductImageAssetValue, ProductImageValue} from "../../../entities/product/types.ts";
import {uploadProductImage} from "../../../shared/api/products.ts";

export interface ResolvedProductImages {
    assetIds: number[]
    urls: string[]
}

const isFile = (value: ProductImageValue): value is File => value instanceof File

const isImageAsset = (value: ProductImageValue): value is ProductImageAssetValue =>
    typeof value === 'object' && value !== null && 'id' in value && 'url' in value

export const resolveProductImages = async (
    images: ProductImageValue[] | undefined
): Promise<ResolvedProductImages> => {
    const resolvedImages = await Promise.all(
        (images ?? []).map(async (image) => {
            if (isFile(image)) {
                const response = await uploadProductImage(image)
                return {id: response.id, url: response.url}
            }

            if (isImageAsset(image)) {
                return {id: image.id, url: image.url}
            }

            throw new Error('Изображение должно быть загруженным asset, а не только URL')
        })
    )

    return {
        assetIds: resolvedImages.map((image) => image.id),
        urls: resolvedImages.map((image) => image.url),
    }
}