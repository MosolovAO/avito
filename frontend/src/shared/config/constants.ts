// Базовый URL API
export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Маршруты приложения
export const ROUTES = {
    HOME: '/',
    PRODUCTS: '/products',
    PRODUCT_EDIT: '/products/:id/edit',
    PRODUCT_ADD: '/products/add'
} as const
