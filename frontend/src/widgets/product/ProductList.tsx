import React, {useEffect, useState} from "react";
import {Table, Button, Space, Tag, Typography, Popconfirm, Tooltip, Input} from "antd";

import {
    PlusOutlined,
    EditOutlined,
    DeleteOutlined,
    PlayCircleOutlined,
    PauseCircleOutlined,
    ThunderboltOutlined
} from "@ant-design/icons";


import type {ColumnsType} from "antd/es/table";
import type {Product} from '../../entities/product'

interface ProductListProps {
    products: Product[]
    loading: boolean
    onAdd: () => void
    onEdit: (id: number) => void
    onDelete: (id: number) => void
    onToggleActive: (id: number, action: 'activate' | 'deactivate') => void
    onGenerate: (id: number) => void
    isToggleActiveLoading: boolean
    toggleActiveTaskId: number | null
}

const {Title, Text} = Typography


const formatTimeLeft = (nextUpdateTime: string | null, now: number): string => {
    if (!nextUpdateTime) return "Не запланировано"

    const nextRunAt = new Date(nextUpdateTime).getTime()

    if (Number.isNaN(nextRunAt)) return "Некорректная дата"

    const diffMs = nextRunAt - now

    if (diffMs <= 0) return "Ожидает запуска"

    const totalMinutes = Math.ceil(diffMs / 60_000)
    const days = Math.floor(totalMinutes / 1440)
    const hours = Math.floor((totalMinutes % 1440) / 60)
    const minutes = totalMinutes % 60

    return [
        days > 0 ? `${days}д` : null,
        days > 0 || hours > 0 ? `${hours}ч` : null,
        `${minutes}м`,
    ].filter(Boolean).join(" ")
}

const useCurrentMinute = () => {
    const [now, setNow] = useState(Date.now())

    useEffect(() => {
        const intervalId = window.setInterval(() => {
            setNow(Date.now())
        }, 60_000)

        return () => window.clearInterval(intervalId)
    }, []);

    return now
}

interface ProductListProps {
    products: Product[]
    loading: boolean
    onAdd: () => void
    onEdit: (id: number) => void
    onDelete: (id: number) => void
    onToggleActive: (id: number, action: 'activate' | 'deactivate') => void
    onGenerate: (id: number) => void
    isToggleActiveLoading: boolean
    toggleActiveTaskId: number | null
}

export const ProductList: React.FC<ProductListProps> = ({
                                                            products,
                                                            loading,
                                                            onAdd,
                                                            onEdit,
                                                            onDelete,
                                                            onToggleActive,
                                                            onGenerate,
                                                            isToggleActiveLoading,
                                                            toggleActiveTaskId,
                                                        }) => {

    const now = useCurrentMinute()
    const [search, setSearch] = useState("")

    const normalizedSearch = search.trim().toLowerCase()

    const filteredProducts = normalizedSearch
        ? products.filter((product) =>
            product.name.toLowerCase().includes(normalizedSearch)
        )
        : products

    const avitoAccountFilters = Array.from(
        new Map(
            products
                .flatMap((product) => product.avito_accounts ?? [])
                .map((account) => [account.id, account])
        ).values()
    ).map((account) => ({
        text: account.name,
        value: String(account.id),
    }))

    const categoryFilters = Array.from(
        new Set(
            products
                .map((product) => product.category?.trim())
                .filter((category): category is string => Boolean(category))
        )
    ).map((category) => ({
        text: category,
        value: category,
    }))

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
            width: 120,
        },
        {
            title: 'Avito',
            key: 'avito_accounts',
            width: 180,
            ellipsis: true,
            filters: avitoAccountFilters,
            filterSearch: true,
            onFilter: (value, product) =>
                product.avito_accounts?.some((account) => String(account.id) === String(value)) ?? false,
            render: (_, product) => {
                const accountNames = product.avito_accounts?.map((account) => account.name) ?? []

                if (accountNames.length === 0) {
                    return <Text type="secondary">Не выбран</Text>
                }

                return (
                    <Text ellipsis>{accountNames.join(', ')}</Text>
                )
            },
        },
        {
            title: 'Категория',
            dataIndex: 'category',
            key: 'category',
            width: 220,
            ellipsis: true,
            filters: categoryFilters,
            filterSearch: true,
            onFilter: (value, product) => product.category === value,
            render: (category: string) => (
                <Text ellipsis>{category}</Text>
            ),
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
            width: 100,
            render: (titles: string[]) => titles?.length || 0,
        },

        {
            title: 'Следующий запуск',
            dataIndex: 'next_update_time',
            key: 'next_update_time',
            width: 190,
            render: (nextUpdateTime: Product['next_update_time']) => (
                <Space orientation="vertical" size={0}>
                    <Text>{formatTimeLeft(nextUpdateTime, now)}</Text>
                    {nextUpdateTime && (
                        <Text type="secondary">{new Date(nextUpdateTime).toLocaleString()}</Text>
                    )}
                </Space>
            ),
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
            width: 160,
            fixed: "right",
            onHeaderCell: () => ({
                style: {
                    paddingLeft: 24,
                    backgroundColor: '#fafafa',
                },
            }),
            onCell: () => ({
                style: {
                    paddingLeft: 24,
                    backgroundColor: '#fafafa',
                },
            }),
            render: (_, record) => {
                const nextAction = record.activate ? 'deactivate' : 'activate'
                const isCurrentTaskLoading = isToggleActiveLoading && toggleActiveTaskId === record.id

                return (
                    <Space size="small" wrap>
                        <Tooltip title={record.activate ? "Задача запущена" : "Задача остановлена"}>
                            <Button
                                size="small"
                                icon={record.activate ? <PlayCircleOutlined/> : <PauseCircleOutlined/>}
                                loading={isCurrentTaskLoading}
                                onClick={() => onToggleActive(record.id, nextAction)}
                                style={{
                                    color: '#fff',
                                    backgroundColor: record.activate ? '#52c41a' : '#ff4d4f',
                                    borderColor: record.activate ? '#52c41a' : '#ff4d4f',
                                }}
                            />
                        </Tooltip>

                        <Tooltip title="Сгенерировать объявления">
                            <Button
                                size="small"
                                type="primary"
                                icon={<ThunderboltOutlined/>}
                                onClick={() => onGenerate(record.id)}
                            />
                        </Tooltip>

                        <Tooltip title="Редактировать задачу">
                            <Button
                                size="small"
                                icon={<EditOutlined/>}
                                onClick={() => onEdit(record.id)}
                            />
                        </Tooltip>

                        <Popconfirm title="Удалить задачу?" onConfirm={() => onDelete(record.id)} okText="Да"
                                    cancelText="Отмена">
                            <Button size="small" danger icon={<DeleteOutlined/>}/>
                        </Popconfirm>
                    </Space>
                )
            },
        },
    ]


    return (
        <Space orientation="vertical" size={16} style={{width: "100%"}}>
            <div style={{display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'center'}}>
                <Title level={2} style={{margin: 0}}>
                    Задачи автогенерации
                </Title>

                <Space>
                    <Input.Search
                        allowClear
                        placeholder="Поиск по названию"
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                        style={{width: 260}}
                    />

                    <Button type="primary" icon={<PlusOutlined/>} onClick={onAdd}>
                        Добавить задачу
                    </Button>
                </Space>
            </div>

            <Table
                columns={columns}
                bordered={true}
                dataSource={filteredProducts}
                rowKey="id"
                loading={loading}
                pagination={{pageSize: 10}}
                size="middle"
                tableLayout="fixed"
                scroll={{x: 1280}}

            />
        </Space>
    )
}