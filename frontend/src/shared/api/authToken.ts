let accessToken: string | null = null
export const getAccessToken = (): string | null => accessToken

export const setAccessToken = (token: string): void => {
    accessToken = token
}

export const clearAccessToken = (): void => {
    accessToken = null
}