import React, { createContext, useContext, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { message } from "antd";
import {
  getMe,
  login,
  logout,
  refreshSession,
  register,
  type AuthUser,
  type LoginRequest,
  type MeResponse,
  type RegisterRequest,
  type WorkspaceContext,
} from "../../../shared/api/auth";

interface AuthContextValue {
  user: AuthUser | null;
  workspaces: WorkspaceContext[];
  isAuthenticated: boolean;
  isChecking: boolean;
  login: (data: LoginRequest) => Promise<void>;
  register: (data: RegisterRequest) => Promise<void>;
  logout: () => Promise<void>;
  loginLoading: boolean;
  registerLoading: boolean;
  logoutLoading: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);
export const authQueryKey = ["auth", ["me"]];

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const queryClient = useQueryClient();

  const sessionQuery = useQuery({
    queryKey: authQueryKey,
    queryFn: refreshSession,
    retry: false,
    staleTime: 5 * 60 * 1000,
  });

  useEffect(() => {
    const handleLogout = () => {
      queryClient.setQueryData(authQueryKey, null);
    };
    window.addEventListener("auth:logout", handleLogout);

    return () => {
      window.removeEventListener("auth:logout", handleLogout);
    };
  }, [queryClient]);

  const loginMutation = useMutation({
    mutationFn: async (data: LoginRequest) => {
      await login(data);
      return getMe();
    },
    onSuccess: (data) => {
      queryClient.setQueryData(authQueryKey, data);
    },
    onError: () => {
      message.error("Неверный email или пароль");
    },
  });

  const registerMutation = useMutation({
    mutationFn: async (data: RegisterRequest) => {
      await register(data);
      return getMe();
    },
    onSuccess: (data) => {
      queryClient.setQueryData(authQueryKey, data);
    },
    onError: () => {
      message.error("Не удалось зарегистрироваться");
    },
  });

  const logoutMutation = useMutation({
    mutationFn: logout,
    onSettled: () => {
      queryClient.setQueryData(authQueryKey, null);
    },
  });

  const session = sessionQuery.data as MeResponse | null | undefined;

  return (
    <AuthContext.Provider
      value={{
        user: session?.user ?? null,
        workspaces: session?.workspaces ?? [],
        isAuthenticated: Boolean(session?.user),
        isChecking: sessionQuery.isLoading,
        login: async (data) => {
          await loginMutation.mutateAsync(data);
        },
        register: async (data) => {
          await registerMutation.mutateAsync(data);
        },
        logout: async () => {
          await logoutMutation.mutateAsync();
        },
        loginLoading: loginMutation.isPending,
        registerLoading: registerMutation.isPending,
        logoutLoading: loginMutation.isPending,
      }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextValue => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }

  return context;
};
