import api from "./axios";
import { clearAccessToken, setAccessToken } from "./authToken";

export interface AuthUser {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
}

export interface WorkspaceContext {
  id: number;
  name: string;
  slug: string;
  role: string;
  status: string;
  permissions: string[];
}

export interface MeResponse {
  user: AuthUser;
  workspaces: WorkspaceContext[];
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RegisterRequest {
  email: string;
  password: string;
  first_name?: string;
  last_name?: string;
  workspace_name: string;
}

interface AccessResponse {
  access: string;
}

export const login = async (data: LoginRequest): Promise<void> => {
  const response = await api.post<AccessResponse>("/api/auth/login/", data);
  setAccessToken(response.data.access);
};

export const register = async (data: RegisterRequest): Promise<void> => {
  const response = await api.post<AccessResponse>("/api/auth/register/", data);
  setAccessToken(response.data.access);
};

export const refreshSession = async (): Promise<MeResponse> => {
  const response = await api.post<AccessResponse>("/api/auth/refresh/");
  setAccessToken(response.data.access);

  return getMe();
};

export const getMe = async (): Promise<MeResponse> => {
  const response = await api.get<MeResponse>("/api/auth/me/");
  return response.data;
};

export const logout = async(): Promise<void> => {
    try {
        await api.post('/api/auth/logout/')
    } finally {
        clearAccessToken()
    }
}