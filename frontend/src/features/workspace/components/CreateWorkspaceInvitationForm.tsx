import React, { useState } from "react";
import { Button, Form, Input, Select, Space, Typography, message } from "antd";
import { CopyOutlined, MailOutlined, SendOutlined } from "@ant-design/icons";
import { useCreateWorkspaceInvitationMutation } from "../model/useWorkspaceUsersQueries";
import {
  createWorkspaceInvitationSchema,
  type CreateWorkspaceInvitationFormValues,
} from "../model/schemas";
import {
  manageableWorkspaceRoles,
  type ManageableWorkspaceRole,
} from "../../../shared/api/workspaceUsers";

interface CreateWorkspaceInvitationFormProps {
  workspaceId: number;
}

const { Text } = Typography;

const roleLabels: Record<ManageableWorkspaceRole, string> = {
  admin: "Администратор",
  manager: "Менеджер",
  analyst: "Аналитик",
  viewer: "Наблюдатель",
};

const createWorkspaceInvitationFieldNames = [
  "email",
  "role",
] as const satisfies readonly (keyof CreateWorkspaceInvitationFormValues)[];

const isCreateWorkspaceInvitationFieldName = (
  value: unknown,
): value is keyof CreateWorkspaceInvitationFormValues =>
  createWorkspaceInvitationFieldNames.some((fieldName) => fieldName === value);

export const CreateWorkspaceInvitationForm: React.FC<
  CreateWorkspaceInvitationFormProps
> = ({ workspaceId }) => {
  const [form] = Form.useForm<CreateWorkspaceInvitationFormValues>();
  const [acceptUrl, setAcceptUrl] = useState<string | null>(null);
  const createInvitationMutation =
    useCreateWorkspaceInvitationMutation(workspaceId);

  const handleFinish = async (values: CreateWorkspaceInvitationFormValues) => {
    const parsed = createWorkspaceInvitationSchema.safeParse(values);

    if (!parsed.success) {
      const fieldErrors = parsed.error.issues
        .map((issue) => {
          const [fieldName] = issue.path;

          if (!isCreateWorkspaceInvitationFieldName(fieldName)) {
            return null;
          }

          return {
            name: fieldName,
            errors: [issue.message],
          };
        })
        .filter((field): field is NonNullable<typeof field> => field !== null);

      form.setFields(fieldErrors);
      return;
    }

    try {
      const invitation = await createInvitationMutation.mutateAsync(
        parsed.data,
      );
      setAcceptUrl(invitation.accept_url);

      form.resetFields();
      message.success("Приглашение отправлено");
    } catch {
      message.error("Не удалось отправить приглашение");
    }
  };

  const handleCopyAcceptUrl = async () => {
    if (!acceptUrl) {
      return;
    }

    try {
      await navigator.clipboard.writeText(acceptUrl);
      message.success("Ссылка скопирована");
    } catch {
      message.error("Не удалось скопировать ссылку");
    }
  };

  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      <Form
        form={form}
        layout="vertical"
        initialValues={{ role: "viewer" }}
        onFinish={handleFinish}>
        <Form.Item name="email" label="Email">
          <Input prefix={<MailOutlined />} placeholder="user@example.com" />
        </Form.Item>

        <Form.Item name="role" label="Роль">
          <Select
            options={manageableWorkspaceRoles.map((role) => ({
              value: role,
              label: roleLabels[role],
            }))}
          />
        </Form.Item>

        <Button
          type="primary"
          htmlType="submit"
          icon={<SendOutlined />}
          loading={createInvitationMutation.isPending}
          block>
          {" "}
          Отправить приглашение
        </Button>
      </Form>

      {acceptUrl && (
        <Space direction="vertical" size={8} style={{ width: "100%" }}>
          <Text type="secondary">Ссылка для принятия приглашения</Text>
          <Input
            value={acceptUrl}
            readOnly
            addonAfter={
              <Button
                type="text"
                size="small"
                icon={<CopyOutlined />}
                onClick={handleCopyAcceptUrl}
              />
            }
          />
        </Space>
      )}
    </Space>
  );
};
