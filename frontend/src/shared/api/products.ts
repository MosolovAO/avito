import api from "./axios.ts";
import type {Product, Product1, ProductOption, ProductFormData, UploadImageResponse} from "../../entities/product";


// Получение всех продуктов
export const getProducts = async (): Promise<Product[]> => {
    const response = await api.get(`/api/products/`)
    return response.data
}

// Получение одного продукта
export const getProduct = async (id: number): Promise<Product> => {
    const response = await api.get(`/api/products/${id}`)
    return response.data
}

// Создание продукта
export const createProduct = async (data: ProductFormData): Promise<Product> => {
    const response = await api.post('/api/products/', data)
    return response.data
}

// Обновление продукта
export const updateProduct = async (id: number, data: ProductFormData): Promise<Product> => {
    const response = await api.patch(`/api/products/${id}/`, data)
    return response.data
}

// Удаление продукта
export const deleteProduct = async (id: number): Promise<void> => {
    await api.delete(`/api/products/${id}`)
}

// Активация/деактивация продукта
export const toggleProductActive = async (id: number, action: 'activate' | 'deactivate'): Promise<{
    status: string;
    active: boolean
}> => {
    const response = await api.post(`/api/toggle-product-active/${id}`, {action})
    return response.data
}

// Получение всех объявлений (Propduct1)
export const getProduct1List = async (): Promise<Product1[]> => {
    const response = await api.get('/api/product1/')
    return response.data
}


// Генерация случайного объявления
export const generateRandomProduct = async (id: number): Promise<any> => {
    const response = await api.post(`/api/product-random/${id}`)
    return response.data
}

// Получение проектов
export const getProjects = async (): Promise<Project[]> => {
    const response = await api.get('/api/projects/')
    return response.data
}

// Получение опций
export const getProductOptions = async (): Promise<ProductOption[]> => {
    const response = await api.get('/api/options/')
    return response.data
}