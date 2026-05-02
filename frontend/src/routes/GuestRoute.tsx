// src/routes/GuestRoute.tsx
import React from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../features/auth/model/AuthProvider";

export const GuestRoute: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const { isAuthenticated } = useAuth();

  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  return children;
};
