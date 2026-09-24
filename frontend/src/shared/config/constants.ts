// Базовый URL API
export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Маршруты приложения
export const ROUTES = {
    HOME: "/",
    PRODUCTS: "/products",
    PRODUCT_EDIT: "/products/:id/edit",
    PRODUCT_ADD: "/products/add",
    AUTOMATIONS: "/automations",
    AUTOMATION_NEW: "/automations/new",
    AUTOMATION_EDIT: "/automations/:automationId/edit",
    AUTOMATION_DETAIL: "/automations/:automationId",
    AUTOMATION_TAB: "/automations/:automationId/:tab",
    AUTOMATION_RUN: "/automation-runs/:runId",
} as const;
