import React from "react";
import { AppstoreOutlined } from "@ant-design/icons";
import { Select, Space, Typography } from "antd";
import { useCurrentWorkspace } from "../model/useCurrentWorkspace";

const { Text } = Typography;

export const WorkspaceSwitcher: React.FC = () => {
  const { currentWorkspaceId, workspaces, setSelectedWorkspaceId } =
    useCurrentWorkspace();

  if (workspaces.length === 0) {
    return <Text type="secondary">Нет кабинета</Text>;
  }

  return (
    <Space size={8}>
        <AppstoreOutlined />
        <Select 
            value={currentWorkspaceId}
            style={{width: 240}}
            options={workspaces.map((workspace) => ({
                value: workspace.id,
                label: workspace.name,
            }))}
            onChange={setSelectedWorkspaceId}
        />
    </Space>
  )
};
