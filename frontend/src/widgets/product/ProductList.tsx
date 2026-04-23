import React from "react";
import {Table, Button, Space, Tag, Typography, Popconfirm} from "antd";
import {PlusOutlined, EditOutlined, DeleteOutlined, ThunderboltOutlined, ThunderboltFilled} from "@ant-design/icons";
import type {ColumnsType} from "antd/es/table";
import type {Product} from '../../entities/product'


const {Title} = Typography

interface ProductListProps {
    products: Product[]
    loading: boolean
    onAdd: () => void
    onEdit: (id: number) => void
    onDelete: (id: number) => void
    onToggleActive: (id: number, action: 'activate' | 'deactivate') => void
    onGenerate: (id: number) => void
}

export const ProductList: React.FC<ProductListProps> = ({
                                                            products,
                                                            loading,
                                                            onAdd,
                                                            onEdit,
                                                            onDelete,
                                                            onToggleActive,
                                                            onGenerate,
                                                        }) => {


    const columns: ColumnsType<Product> = [
        {
            title: 'ID',
            dataIndex: 'id',
            key: 'id',
            width: 70,
            sorter: (a, b) => a.id - b.id,
            defaultSortOrder: 'ascend'
        },
        {
            title: 'Название',
            dataIndex: 'name',
            key: 'name',
            ellipsis: true,
        },
        {
            title: 'Категория',
            dataIndex: 'category',
            key: 'category',
            width: 120,
        },
        {
            title: 'Цена',
            dataIndex: 'price',
            key: 'price',
            width: 100,
            render: (price: number) => `${price} ₽`,
        },
        {
            title: 'Заголовков',
            dataIndex: 'titles',
            key: 'titles_count',
            width: 130,
            render: (titles: string[]) => titles?.length || 0,
        },
        {
            title: 'Статус',
            dataIndex: 'activate',
            key: 'activate',
            width: 100,
            render: (active: boolean) => (
                <Tag color={active ? 'green' : 'red'}>
                    {active ? 'Активен' : 'Неактивен'}
                </Tag>
            ),
        },
        {
            title: 'Действия',
            key: 'actions',
            width: 240,
            render: (_, record) => (
                <Space size="small">
                    <Button
                        size="small"
                        type="primary"
                        icon={record.activate ? <ThunderboltFilled/> : <ThunderboltOutlined/>}
                        onClick={() => onToggleActive(record.id, record.activate ? 'deactivate' : 'activate')}
                    />
                    <Button
                        size="small"
                        icon={<EditOutlined/>}
                        onClick={() => onEdit(record.id)}
                    />
                    <Button
                        size="small"
                        type="primary"
                        onClick={() => onGenerate(record.id)}
                    >
                        Генерировать
                    </Button>
                    <Popconfirm
                        title="Удалить продукт?"
                        onConfirm={() => onDelete(record.id)}
                        okText="Да"
                        cancelText="Отмена"
                    >
                        <Button size="small" danger icon={<DeleteOutlined/>}/>
                    </Popconfirm>
                </Space>
            ),
        },
    ]


    return (
        <div style={{padding: '24px'}}>
            <div style={{display: ' flex', justifyContent: 'space-between', marginBottom: '16px'}}>
                <Title level={2}>Продукты</Title>
                <Button type="primary" icon={<PlusOutlined/>} onClick={onAdd}>
                    Добавить продукт
                </Button>
            </div>
            <Table
                columns={columns}
                dataSource={products}
                rowKey="id"
                loading={loading}
                pagination={{pageSize: 10}}
            />

        </div>
    )
}