import React from 'react'
import {Layout as AntLayout, Menu} from 'antd'
import {HomeOutlined, ProductOutlined, FolderOutlined} from '@ant-design/icons'
import {useNavigate, useLocation} from 'react-router-dom'

const {Header, Content, Footer} = AntLayout

interface LayoutProps {
    children: React.ReactNode
}

export const Layout: React.FC<LayoutProps> = ({children}) => {
    const navigate = useNavigate()
    const location = useLocation()

    const getMenuKey = () => {
        if (location.pathname === '/home') return 'home'
        if (location.pathname.startsWith('/products')) return 'products'
        if (location.pathname.startsWith('/projects')) return 'projects'
        return 'products'
    }

    const menuItems = [
        {
            key: 'home',
            icon: <HomeOutlined/>,
            label: 'Главная',
            onClick: () => navigate('/home'),
        },
        {
            key: 'products',
            icon: <ProductOutlined/>,
            label: 'Продукты',
            onClick: () => navigate('/products'),
        },
         {
           key: 'projects',
           icon: <FolderOutlined />,
           label: 'Проекты',
           onClick: () => navigate('/projects'),
         },

    ]

    return (
        <AntLayout style={{minHeight: '100vh'}}>
            <Header style={{display: 'flex', alignItems: 'center'}}>
                <div style={{color: 'white', fontSize: '20px', marginRight: '24px'}}>
                    Avito Parser
                </div>
                <Menu
                    theme="dark"
                    mode="horizontal"
                    selectedKeys={[getMenuKey()]}
                    items={menuItems}
                />
            </Header>
            <Content style={{padding: '0 48px'}}>
                {children}
            </Content>
            <Footer style={{textAlign: 'center'}}>
                Avito Parser ©{new Date().getFullYear()} Created with React + Ant Design
            </Footer>
        </AntLayout>
    )
}
