import React, { useState } from "react";

import {
  AppstoreOutlined,
  FolderOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MessageOutlined,
  ProductOutlined,
  RobotOutlined,
  UserOutlined,
  WalletOutlined,
  LogoutOutlined,
  TeamOutlined,
} from "@ant-design/icons";
import {
  Avatar,
  Button,
  Dropdown,
  Layout as AntLayout,
  Menu,
  Space,
  Tag,
  Typography,
  theme,
} from "antd";
import type { MenuProps } from "antd";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../../features/auth/model/AuthProvider";
import { WorkspaceSwitcher } from "../../features/workspace/components";

const { Header, Content, Sider } = AntLayout;
const { Text, Title } = Typography;

interface LayoutProps {
  children: React.ReactNode;
}

type MenuKey =
  | "workspace"
  | "users"
  | "products"
  | "projects"
  | "chats"
  | "bots";

const menuItems: MenuProps["items"] = [
  {
    key: "workspace",
    icon: <AppstoreOutlined />,
    label: "Рабочее пространство",
  },
  {
    key: "users",
    icon: <TeamOutlined />,
    label: "Пользователи",
  },
  {
    key: "products",
    icon: <ProductOutlined />,
    label: "Продукты",
  },
  {
    key: "projects",
    icon: <FolderOutlined />,
    label: "Проекты",
  },
  {
    key: "chats",
    icon: <MessageOutlined />,
    label: "Чаты",
  },
  {
    key: "bots",
    icon: <RobotOutlined />,
    label: "Боты",
  },
];

const routeByMenuKey: Record<MenuKey, string> = {
  workspace: "/",
  users: "/workspace/users",
  products: "/products",
  projects: "/projects",
  chats: "/chats",
  bots: "/bots",
};

const userMenuItems: MenuProps["items"] = [
  {
    key: "profile",
    label: "Профиль скоро появится",
    disabled: true,
  },
  {
    key: "settings",
    label: "Настройки скоро появятся",
    disabled: true,
  },
];

const getSelectedMenuKey = (pathname: string): MenuKey => {
  if (pathname.startsWith("/workspace/users")) return "users";
  if (pathname.startsWith("/products")) return "products";
  if (pathname.startsWith("/projects")) return "projects";
  if (pathname.startsWith("/chats")) return "chats";
  if (pathname.startsWith("/bots")) return "bots";

  return "workspace";
};

export const Layout: React.FC<LayoutProps> = ({ children }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const { token } = theme.useToken();

  const selectedMenuKey = getSelectedMenuKey(location.pathname);

  const handleMenuClick: MenuProps["onClick"] = ({ key }) => {
    navigate(routeByMenuKey[key as MenuKey]);
  };

  const { user, logout, logoutLoading } = useAuth();

  const userMenuItems: MenuProps["items"] = [
    {
      key: "logout",
      icon: <LogoutOutlined />,
      label: "Выйти",
    },
  ];

  const handleUserMenuClick: MenuProps["onClick"] = async ({ key }) => {
    if (key === "logout") {
      await logout();
      navigate("/login", { replace: true });
    }
  };

  return (
    <AntLayout hasSider style={{ minHeight: "100vh" }}>
      <Sider
        collapsed={collapsed}
        collapsedWidth={88}
        trigger={null}
        width={260}
        theme="dark">
        <div
          onClick={() => navigate("/")}
          style={{
            height: 72,
            padding: collapsed ? "16px 20px" : "16px 18px",
            display: "flex",
            alignItems: "center",
            cursor: "pointer",
            borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
          }}>
          <Space size={12}>
            <div
              style={{
                width: 40,
                height: 40,
                borderRadius: 12,
                background: token.colorPrimary,
                color: token.colorWhite,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontWeight: 700,
                fontSize: 16,
              }}>
              AP
            </div>
            {!collapsed && (
              <div style={{ display: "flex", flexDirection: "column" }}>
                <Text strong style={{ color: "rgba(255, 255, 255, 0.95)" }}>
                  Avito Parser
                </Text>
                <Text
                  style={{ fontSize: 12, color: "rgba(255, 255, 255, 0.45)" }}>
                  Рабочее пространство
                </Text>
              </div>
            )}
          </Space>
        </div>

        <Menu
          mode="inline"
          theme="dark"
          selectedKeys={[selectedMenuKey]}
          items={menuItems}
          onClick={handleMenuClick}
          style={{ paddingTop: 8, borderInlineEnd: 0 }}
        />
      </Sider>

      <AntLayout>
        <Header
          style={{
            padding: "0 24px",
            background: token.colorBgContainer,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
          }}>
          <Space size={16}>
            <Button
              type="text"
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setCollapsed((previous) => !previous)}
            />
            <WorkspaceSwitcher />
          </Space>

          <Space size={12}>
            <Tag
              icon={<WalletOutlined />}
              color="processing"
              style={{
                marginInlineEnd: 0,
                paddingInline: 12,
                lineHeight: "30px",
              }}>
              Баланс: 12 400 ₽
            </Tag>
            <Button type="primary">Пополнить</Button>
            <Dropdown
              menu={{ items: userMenuItems, onClick: handleUserMenuClick }}
              placement="bottomRight"
              trigger={["click"]}>
              <Button type="text" loading={logoutLoading}>
                <Space size={10}>
                  <Avatar size="small" icon={<UserOutlined />} />
                  <Text>{user?.email ?? "Пользователь"}</Text>
                </Space>
              </Button>
            </Dropdown>
          </Space>
        </Header>

        <Content
          style={{
            padding: 24,
            background: token.colorBgLayout,
          }}>
          {children}
        </Content>
      </AntLayout>
    </AntLayout>
  );
};
