import type {UploadFile} from "antd";
import {uploadProductImage} from "../../../shared/api/products";

export const MAX_AD_IMAGE_FILES = 10;
export const MAX_AD_IMAGE_FILE_SIZE = 2 * 1024 * 1024;
export const TEMPORARY_PREVIEW_URL_TTL_MS = 60 * 1000;
export const ALLOWED_AD_IMAGE_TYPES = ["image/jpeg", "image/png"];

export const getAdImageValidationError = (file: File): string | null => {
    if (!ALLOWED_AD_IMAGE_TYPES.includes(file.type)) {
        return "Можно загружать только JPEG или PNG изображения";
    }

    if (file.size > MAX_AD_IMAGE_FILE_SIZE) {
        return "Размер файла не должен превышать 2MB";
    }

    return null;
};

export const resolveAdImageUrls = async (files: UploadFile[]): Promise<string[]> => {
    return Promise.all(files.map(async (file) => {
        if (file.url) {
            return file.url;
        }

        if (!file.originFileObj) {
            throw new Error("Не удалось прочитать файл изображения");
        }

        const response = await uploadProductImage(file.originFileObj);
        return response.url;
    }));
};

export const revokeTemporaryPreviewUrl = (url: string): void => {
    window.setTimeout(() => {
        URL.revokeObjectURL(url);
    }, TEMPORARY_PREVIEW_URL_TTL_MS);
};
