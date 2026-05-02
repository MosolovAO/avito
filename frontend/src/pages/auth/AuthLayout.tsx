import React from "react";
import { Layout } from "antd";

export const AuthLayout: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  return (
    <Layout
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
      }}>
      {children}
    </Layout>
  );
};
