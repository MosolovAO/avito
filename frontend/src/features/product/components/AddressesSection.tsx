// src/features/product/components/AddressesSection.tsx
import React, {useState} from 'react'
import {Button, Card, Form, Input, Space, Table, Typography} from 'antd'
import {DeleteOutlined, PlusOutlined} from '@ant-design/icons'
import type {ColumnsType} from 'antd/es/table'
import type {ProductFormValues} from '../lib/productFormMapper'

const {TextArea} = Input
const {Text} = Typography

const EMPTY_ADDRESSES: string[] = []

interface AddressRow {
    key: string
    index: number
    address: string
}

export const AddressesSection: React.FC = () => {
    const form = Form.useFormInstance<ProductFormValues>()
    const watchedAddresses = Form.useWatch('addresses', {form, preserve: true})
    const addresses = watchedAddresses ?? EMPTY_ADDRESSES

    const [bulkInput, setBulkInput] = useState('')

    const handleAddBulk = () => {
        const nextAddresses = bulkInput
            .split('\n')
            .map((line) => line.trim())
            .filter(Boolean)

        if (nextAddresses.length === 0) {
            return
        }

        form.setFieldValue('addresses', [...addresses, ...nextAddresses])
        setBulkInput('')
    }

    const handleRemove = (indexToRemove: number) => {
        form.setFieldValue(
            'addresses',
            addresses.filter((_, index) => index !== indexToRemove)
        )
    }

    const columns: ColumnsType<AddressRow> = [
        {
            title: 'Адрес',
            dataIndex: 'address',
            key: 'address',
            width: 500,
            render: (address: string) => <Text>{address}</Text>,
        },
        {
            title: 'Действия',
            key: 'actions',
            width: 150,
            align: 'right',
            render: (_, record) => (
                <Space>
                    <Button size="small">Рекламная ставка</Button>
                    <Button
                        size="small"
                        danger
                        icon={<DeleteOutlined/>}
                        onClick={() => handleRemove(record.index)}
                    />
                </Space>
            ),
        },
    ]

    const dataSource: AddressRow[] = addresses.map((address, index) => ({
        key: `${index}-${address}`,
        index,
        address,
    }))

    return (
        <Card title="📍 Адреса" style={{marginBottom: 16}}>
            <Space direction="vertical" style={{width: '100%'}} size="middle">
                <div>
                    <TextArea
                        rows={3}
                        placeholder="Массовое добавление (каждый адрес с новой строки)"
                        value={bulkInput}
                        onChange={(event) => setBulkInput(event.target.value)}
                    />

                    <Button
                        type="default"
                        icon={<PlusOutlined/>}
                        onClick={handleAddBulk}
                        disabled={!bulkInput.trim()}
                        style={{marginTop: 8}}
                    >
                        Добавить все адреса
                    </Button>
                </div>

                {addresses.length > 0 && (
                    <Table
                        columns={columns}
                        dataSource={dataSource}
                        pagination={false}
                        size="small"
                        scroll={{y: 300}}
                        style={{marginTop: 30}}
                    />
                )}
            </Space>
        </Card>
    )
}
