import React from "react";
import { Card, Col, Result, Row, Space, Typography } from "antd";
import {
  CreateWorkspaceInvitationForm,
  WorkspaceMembersTable,
  WorkspaceInvitationsTable,
} from "../../features/workspace/components";
import { useCurrentWorkspace } from "../../features/workspace/model/useCurrentWorkspace";

const { Title, Text } = Typography;

export const WorkspaceUsersPage: React.FC = () => {
  const { currentWorkspace, canManageUsers } = useCurrentWorkspace();

  if (!currentWorkspace) {
    return <Result status="404" title="Кабинет не выбран" />;
  }
  if (!canManageUsers) {
    return <Result status="403" title="Недостаточно прав" />;
  }

  return (
    <Space direction="vertical" size={24} style={{ width: "100%" }}>
      <div>
        <Title level={2} style={{ marginBottom: 4 }}>
          Пользователи
        </Title>
        <Text type="secondary">{currentWorkspace.name}</Text>
      </div>

      <Row gutter={[24, 25]}>
        <Col xs={24} xl={14}>
          <Card title="Участники">
            <WorkspaceMembersTable workspaceId={currentWorkspace.id} />
          </Card>
        </Col>
        <Col xs={24} xl={10}>
          <Card title="Приглашения">
            <CreateWorkspaceInvitationForm workspaceId={currentWorkspace.id} />
            <WorkspaceInvitationsTable workspaceId={currentWorkspace.id} />
          </Card>
        </Col>
      </Row>
    </Space>
  );
};
