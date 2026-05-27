import React, {useState} from "react";

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
    DatabaseOutlined,
    FileTextOutlined,
    HistoryOutlined,
    AppstoreAddOutlined,
    PlusSquareOutlined,
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
import type {MenuProps} from "antd";
import {useLocation, useNavigate} from "react-router-dom";
import {useAuth} from "../../features/auth/model/AuthProvider";
import {WorkspaceSwitcher} from "../../features/workspace/components";

const {Header, Content, Sider} = AntLayout;
const {Text, Title} = Typography;

interface LayoutProps {
    children: React.ReactNode;
}

type MenuKey =
    | "workspace"
    | "users"
    | "products"
    | "projects"
    | "avitoListings"
    | "adPublications"
    | "adBatches"
    | "adCreatives"
    | "chats"
    | "manualMassPosting"
    | "bots"
    | "avitoAds";


const menuItems: MenuProps["items"] = [
    {
        key: "workspace",
        icon: <AppstoreOutlined/>,
        label: "Рабочее пространство",
    },
    {
        key: "ads",
        icon: <DatabaseOutlined/>,
        label: "Объявления",
        children: [
            {
                key: "avitoAds",
                icon: <DatabaseOutlined/>,
                label: "Все объявления",
            },
            {
                key: "manualMassPosting",
                icon: <PlusSquareOutlined/>,
                label: "Маспостинг",
            },
            {
                key: "adCreatives",
                icon: <AppstoreAddOutlined/>,
                label: "Креативы",
            },
            {
                key: "products",
                icon: <ProductOutlined/>,
                label: "Задачи автогенерации",
            },
            {
                key: "avitoListings",
                icon: <DatabaseOutlined/>,
                label: "Объявления авито",
            },
            {
                key: "adPublications",
                icon: <FileTextOutlined/>,
                label: "Публикации",
            },
        ],
    },
    {
        key: "users",
        icon: <TeamOutlined/>,
        label: "Пользователи",
    },
    {
        key: "adBatches",
        icon: <HistoryOutlined/>,
        label: "Операции",
    },
    {
        key: "projects",
        icon: <FolderOutlined/>,
        label: "Проекты",
    },
    {
        key: "chats",
        icon: <MessageOutlined/>,
        label: "Чаты",
    },
    {
        key: "bots",
        icon: <RobotOutlined/>,
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
    avitoListings: "/avito/listings",
    adPublications: "/ads/publications",
    adBatches: "/ads/batches",
    adCreatives: "/ads/creatives",
    manualMassPosting: "/manual-mass-posting/new",
    avitoAds: "/ads",
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
    if (pathname.startsWith("/avito/listings")) return "avitoListings";
    if (pathname.startsWith("/ads/publications")) return "adPublications";
    if (pathname.startsWith("/ads/batches")) return "adBatches";
    if (pathname.startsWith("/ads/creatives")) return "adCreatives";
    if (pathname.startsWith("/manual-mass-posting")) return "manualMassPosting";
    if (pathname === "/ads") return "avitoAds";

    return "workspace";
};

export const Layout: React.FC<LayoutProps> = ({children}) => {
    const navigate = useNavigate();
    const location = useLocation();
    const [collapsed, setCollapsed] = useState(false);
    const {token} = theme.useToken();

    const selectedMenuKey = getSelectedMenuKey(location.pathname);

    const handleMenuClick: MenuProps["onClick"] = ({key}) => {
        navigate(routeByMenuKey[key as MenuKey]);
    };

    const {user, logout, logoutLoading} = useAuth();

    const userMenuItems: MenuProps["items"] = [
        {
            key: "logout",
            icon: <LogoutOutlined/>,
            label: "Выйти",
        },
    ];

    const handleUserMenuClick: MenuProps["onClick"] = async ({key}) => {
        if (key === "logout") {
            await logout();
            navigate("/login", {replace: true});
        }
    };

    return (
        <AntLayout hasSider style={{height: "100vh", overflow: "hidden"}}>
            <Sider
                collapsed={collapsed}
                collapsedWidth={88}
                trigger={null}
                width={260}
                theme="dark"
                style={{height: "100vh", overflow: "hidden"}}>
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
                            <div style={{display: "flex", flexDirection: "column"}}>
                                <Text strong style={{color: "rgba(255, 255, 255, 0.95)"}}>
                                    Avito Parser
                                </Text>
                                <Text
                                    style={{fontSize: 12, color: "rgba(255, 255, 255, 0.45)"}}>
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
                    defaultOpenKeys={["ads"]}
                    items={menuItems}
                    onClick={handleMenuClick}
                    style={{
                        paddingTop: 8,
                        borderInlineEnd: 0,
                        height: "calc(100vh - 72px)",
                        overflowY: "auto",
                        overflowX: "hidden",
                    }}
                />
            </Sider>

            <AntLayout style={{height: "100vh", minWidth: 0, overflow: "hidden"}}>
                <Header
                    style={{
                        padding: "0 24px",
                        background: token.colorBgContainer,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        borderBottom: `1px solid ${token.colorBorderSecondary}`,
                        flexShrink: 0,
                    }}>
                    <Space size={16}>
                        <Button
                            type="text"
                            icon={collapsed ? <MenuUnfoldOutlined/> : <MenuFoldOutlined/>}
                            onClick={() => setCollapsed((previous) => !previous)}
                        />
                        <WorkspaceSwitcher/>
                    </Space>

                    <Space size={12}>
                        <Tag
                            icon={<WalletOutlined/>}
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
                            menu={{items: userMenuItems, onClick: handleUserMenuClick}}
                            placement="bottomRight"
                            trigger={["click"]}>
                            <Button type="text" loading={logoutLoading}>
                                <Space size={10}>
                                    <Avatar size="small" icon={<UserOutlined/>}/>
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
                        overflow: "auto",
                        minHeight: 0,
                    }}>
                    {children}
                </Content>
            </AntLayout>
        </AntLayout>
    );
};
