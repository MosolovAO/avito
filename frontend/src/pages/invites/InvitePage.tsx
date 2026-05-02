// /Users/artem/Desktop/avito/frontend/src/pages/invites/InvitePage.tsx
import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams, Link, useLocation } from "react-router-dom";

import {
  Alert,
  Card,
  Descriptions,
  message,
  Result,
  Space,
  Spin,
  Tag,
  Typography,
  Button,
} from "antd";
import { RegisterByInvitationForm } from "../../features/auth/components/RegisterByInvitationForm";
import {
  acceptWorkspaceInvitation,
  getPublicWorkspaceInvitation,
  workspaceInvitationsKeys,
  type WorkspaceInvitationStatus,
  type WorkspaceRole,
} from "../../shared/api/workspaceUsers";

import { authQueryKey, useAuth } from "../../features/auth/model/AuthProvider";

const { Title, Text } = Typography;

const roleLabels: Record<WorkspaceRole, string> = {
  owner: "Владелец",
  admin: "Администратор",
  manager: "Менеджер",
  analyst: "Аналитик",
  viewer: "Наблюдатель",
};

const statusLabels: Record<WorkspaceInvitationStatus, string> = {
  pending: "Активно",
  accepted: "Принято",
  revoked: "Отозвано",
  expired: "Истекло",
};

const statusColors: Record<WorkspaceInvitationStatus, string> = {
  pending: "processing",
  accepted: "success",
  revoked: "default",
  expired: "warning",
};

const formatDateTime = (value: string): string => {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
};

export const InvitePage: React.FC = () => {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const { isAuthenticated, user } = useAuth();

  const acceptInvitationMutation = useMutation({
    mutationFn: () => acceptWorkspaceInvitation(token ?? ""),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: authQueryKey });
      await queryClient.invalidateQueries({
        queryKey: token
          ? workspaceInvitationsKeys.detail(token)
          : workspaceInvitationsKeys.all,
      });

      message.success("Приглашение принято");
      navigate("/", { replace: true });
    },
    onError: () => {
      message.error("Не удалось принять приглашение");
    },
  });

  const inviteQuery = useQuery({
    queryKey: token
      ? workspaceInvitationsKeys.detail(token)
      : workspaceInvitationsKeys.all,
    queryFn: () => getPublicWorkspaceInvitation(token ?? ""),
    enabled: Boolean(token),
    retry: false,
  });

  if (!token) {
    return <Result status="404" title="Приглашение не найдено" />;
  }

  if (inviteQuery.isLoading) {
    return (
      <div
        style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>
        <Spin size="large" />
      </div>
    );
  }

  if (inviteQuery.isError || !inviteQuery.data) {
    return <Result status="404" title="Приглашение не найдено" />;
  }

  const invitation = inviteQuery.data;
  const isPending = invitation.status === "pending";

  const isEmailMatched =
    isAuthenticated &&
    user?.email.toLowerCase() === invitation.email.toLowerCase();

  const canAccept = isPending && isAuthenticated && isEmailMatched;

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: 24,
        background: "#f5f5f5",
      }}>
      <Card style={{ width: "100%", maxWidth: 560 }}>
        <Space direction="vertical" size={20} style={{ width: "100%" }}>
          <div>
            <Title level={3} style={{ marginBottom: 4 }}>
              Приглашение в кабинет
            </Title>
            <Text type="secondary">
              Проверьте данные приглашения перед продолжением
            </Text>
          </div>

          {!isPending && (
            <Alert
              type="warning"
              showIcon
              message="Это приглашение уже недоступно"
            />
          )}

          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="Кабинет">
              {invitation.workspace.name}
            </Descriptions.Item>
            <Descriptions.Item label="Email">
              {invitation.email}
            </Descriptions.Item>
            <Descriptions.Item label="Роль">
              {roleLabels[invitation.role]}
            </Descriptions.Item>
            <Descriptions.Item label="Статус">
              <Tag color={statusColors[invitation.status]}>
                {statusLabels[invitation.status]}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Действует до">
              {formatDateTime(invitation.expires_at)}
            </Descriptions.Item>
          </Descriptions>

          {isPending && !isAuthenticated && (
            <Space direction="vertical" size={16} style={{ width: "100%" }}>
              <Alert
                type="info"
                showIcon
                message="Создайте аккаунт или войдите, чтобы принять приглашение"
              />

              <RegisterByInvitationForm token={token} />

              <Link to="/login" state={{ from: location }}>
                <Button block>Уже есть аккаунт</Button>
              </Link>
            </Space>
          )}

          {isPending && isAuthenticated && !isEmailMatched && (
            <Alert
              type="warning"
              showIcon
              message="Приглашение создано для другого email"
              description={`Вы вошли как ${user?.email ?? "другой пользователь"}.`}
            />
          )}

          {isPending && isAuthenticated && (
            <Space style={{ width: "100%", justifyContent: "flex-end" }}>
              <Button
                type="primary"
                disabled={!canAccept}
                loading={acceptInvitationMutation.isPending}
                onClick={() => {
                  acceptInvitationMutation.mutate();
                }}>
                Принять приглашение
              </Button>
            </Space>
          )}
        </Space>
      </Card>
    </div>
  );
};
