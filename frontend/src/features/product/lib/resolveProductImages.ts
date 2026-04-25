import type {ProductImageValue} from "../../../entities/product/types.ts";
import {uploadProductImage} from "../../../shared/api/products.ts";

const isFile = (value: ProductImageValue): value is File => value instanceof File

export const resolveProductImages = async (
    images: ProductImageValue[] | undefined
): Promise<string[]> => {
    const resolvedImages = await Promise.all(
        (images ?? []).map(async(image) => {
            if(!isFile(image)) {
                return image
            }

            const response = await uploadProductImage(image)
            return response.url
        })
    )

    return resolvedImages.filter(Boolean)
}