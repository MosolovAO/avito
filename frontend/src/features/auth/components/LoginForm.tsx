// src/features/auth/components/LoginForm.tsx
import React from "react";
import { Button, Form, Input } from "antd";
import { LockOutlined, MailOutlined } from "@ant-design/icons";
import { loginSchema, type LoginFormValues } from "../model/schemas";

interface LoginFormProps {
  loading: boolean;
  onSubmit: (values: LoginFormValues) => Promise<void>;
}

export const LoginForm: React.FC<LoginFormProps> = ({ loading, onSubmit }) => {
  const [form] = Form.useForm<LoginFormValues>();

  const handleFinish = async (values: LoginFormValues) => {
    const parsed = loginSchema.safeParse(values);

    if (!parsed.success) {
      form.setFields(
        parsed.error.issues.map((issue) => ({
          name: issue.path,
          errors: [issue.message],
        })),
      );
      return;
    }

    await onSubmit(parsed.data);
  };

  return (
    <Form form={form} layout="vertical" onFinish={handleFinish}>
      <Form.Item name="email" label="Email">
        <Input prefix={<MailOutlined />} placeholder="user@example.com" />
      </Form.Item>

      <Form.Item name="password" label="Пароль">
        <Input.Password prefix={<LockOutlined />} placeholder="Пароль" />
      </Form.Item>

      <Button type="primary" htmlType="submit" block loading={loading}>
        Войти
      </Button>
    </Form>
  );
};
