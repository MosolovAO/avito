import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button, Col, Form, Input, Row, message } from "antd";
import { LockOutlined, UserOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { registerByWorkspaceInvitation } from "../../../shared/api/workspaceUsers";
import { authQueryKey } from "../model/AuthProvider";
import {
  registerByInvitationSchema,
  type RegisterByInvitationFormValues,
} from "../model/schemas";

interface RegisterByInvitationFormProps {
  token: string;
}

export const RegisterByInvitationForm: React.FC<
  RegisterByInvitationFormProps
> = ({ token }) => {
  const [form] = Form.useForm<RegisterByInvitationFormValues>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const registerMutation = useMutation({
    mutationFn: async (values: RegisterByInvitationFormValues) => {
      const parsed = registerByInvitationSchema.safeParse(values);
      if (!parsed.success) {
        form.setFields(
          parsed.error.issues.map((issue) => ({
            name: issue.path.map(String),
            errors: [issue.message],
          })),
        );
        return null;
      }

      const { confirmPassword, ...request } = parsed.data;
      return registerByWorkspaceInvitation(token, request);
    },
    onSuccess: async (result) => {
      if (!result) {
        return;
      }

      await queryClient.invalidateQueries({ queryKey: authQueryKey });
      message.success("Аккаунт создан");
      navigate("/", { replace: true });
    },
    onError: () => {
      message.error("Не удалось создать аккаунт");
    },
  });

  const handleFinish = async (values: RegisterByInvitationFormValues) => {
    await registerMutation.mutateAsync(values);
  };

  return (
    <Form form={form} layout="vertical" onFinish={handleFinish}>
      <Row gutter={12}>
        <Col span={12}>
          <Form.Item name="first_name" label="Имя">
            <Input prefix={<UserOutlined />} />
          </Form.Item>
        </Col>

        <Col span={12}>
          <Form.Item name="last_name" label="Фамилия">
            <Input prefix={<UserOutlined />} />
          </Form.Item>
        </Col>
      </Row>

      <Form.Item name="password" label="Пароль">
        <Input.Password prefix={<LockOutlined />} />
      </Form.Item>

      <Form.Item name="confirmPassword" label="Повтор пароля">
        <Input.Password prefix={<LockOutlined />} />
      </Form.Item>

      <Button
        type="primary"
        htmlType="submit"
        loading={registerMutation.isPending}
        block>
        Создать аккаунт и принять приглашение
      </Button>
    </Form>
  );
};
