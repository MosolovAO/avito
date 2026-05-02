import React from "react";
import { Card, Space, Typography } from "antd";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { LoginForm } from "../../features/auth/components/LoginForm";
import { useAuth } from "../../features/auth/model/AuthProvider";
import type { LoginFormValues } from "../../features/auth/model/schemas";

const { Title, Text } = Typography;

interface LoginLocationState {
  from?: {
    pathname: string;
  };
}

export const LoginPage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { login, loginLoading } = useAuth();

  const state = location.state as LoginLocationState | null;
  const redirectPath = state?.from?.pathname ?? "/";

  const handleSubmit = async (values: LoginFormValues) => {
    await login(values);
    navigate(redirectPath, { replace: true });
  };

  return (
    <Card style={{ width: 420 }}>
      <Space direction="vertical" size={20} style={{ width: "100%" }}>
        <div>
          <Title level={3} style={{ marginBottom: 4 }}>
            Вход
          </Title>
          <Text type="secondary">Войдите в рабочее пространство</Text>
        </div>

        <LoginForm loading={loginLoading} onSubmit={handleSubmit} />

        <Text>
          Нет аккаунта? <Link to="/register">Зарегистрироваться</Link>
        </Text>
      </Space>
    </Card>
  );
};
