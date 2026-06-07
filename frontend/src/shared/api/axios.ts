import axios, {type AxiosError, type AxiosRequestConfig} from 'axios'
import {clearAccessToken, getAccessToken, setAccessToken} from './authToken'

interface RetryableRequestConfig extends AxiosRequestConfig {
    _retry?: boolean
}

interface AccessResponse {
    access: string
}

const baseURL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const refreshClient = axios.create({
    baseURL,
    withCredentials: true
})

let refreshPromise: Promise<string> | null = null

const refreshAccessToken = async (): Promise<string> => {
    if (!refreshPromise) {
        refreshPromise = refreshClient
            .post<AccessResponse>('/api/auth/refresh/')
            .then((response) => {
                setAccessToken(response.data.access)
                return response.data.access
            })
            .finally(() => {
                refreshPromise = null
            })
    }

    return refreshPromise
}

// Создаём экземпляр axios с базовыми настройками
const api = axios.create({
    baseURL,
    withCredentials: true,
    headers: {
        'Content-Type': 'application/json',
    },
})

// Добавляем interceptor для обработки ошибок
api.interceptors.request.use((config) => {
    const token = getAccessToken()

    if (token) {
        config.headers.Authorization = `Bearer ${token}`
    }

    return config
})

api.interceptors.response.use(
    (response) => response,
    async (error: AxiosError) => {
        const originalRequest = error.config as RetryableRequestConfig | undefined
        const isRefreshRequest = originalRequest?.url === '/api/auth/refresh/'

        if (error.response?.status !== 401 || !originalRequest || originalRequest?._retry || isRefreshRequest) {
            return Promise.reject(error)
        }

        originalRequest._retry = true

        try {
            const access = await refreshAccessToken()

            originalRequest.headers = {
                ...originalRequest.headers,
                Authorization: `Bearer ${access}`,
            }

            return api(originalRequest)
        } catch (refreshError) {
            clearAccessToken()
            window.dispatchEvent(new Event('auth:logout'))
            return Promise.reject(refreshError)
        }
    }
)

export default api



