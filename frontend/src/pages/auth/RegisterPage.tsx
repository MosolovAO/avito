import React from "react";
import { Card, Space, Typography } from "antd";
import { Link, useNavigate } from "react-router-dom";
import { RegisterForm } from "../../features/auth/components/RegisterForm";
import { useAuth } from "../../features/auth/model/AuthProvider";
import type { RegisterFormValues } from "../../features/auth/model/schemas";

const { Title, Text } = Typography;

export const RegisterPage: React.FC = () => {
  const navigate = useNavigate();
  const { register, registerLoading } = useAuth();

  const handleSubmit = async ({
    confirmPassword,
    ...values
  }: RegisterFormValues) => {
    await register(values);
    navigate("/", { replace: true });
  };

  return (
    <Card style={{ width: 520 }}>
      <Space direction="vertical" size={20} style={{ width: "100%" }}>
        <div>
          <Title level={3} style={{ marginBottom: 4 }}>
            Регистрация
          </Title>
          <Text type="secondary">Создайте аккаунт и первый кабинет</Text>
        </div>

        <RegisterForm loading={registerLoading} onSubmit={handleSubmit} />

        <Text>
          Уже есть аккаунт? <Link to="/login">Войти</Link>
        </Text>
      </Space>
    </Card>
  );
};
