import React from "react";
import { Spin } from "antd";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../features/auth/model/AuthProvider";

export const ProtectedRoute: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const location = useLocation();
  const { isAuthenticated, isChecking } = useAuth();

  if (isChecking) {
    return (
      <div
        style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>
        <Spin size="large" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return children;
};
