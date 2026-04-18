import React, {useState} from 'react'
import {Input, Button, Space, Card, Typography, Table} from 'antd'
import {PlusOutlined, DeleteOutlined} from '@ant-design/icons'
import type {ColumnsType} from 'antd/es/table'


const {TextArea} = Input
const {Text} = Typography

interface AddressItem {
    key: string
    address: string
}

interface AddressesSectionProps {
    initialAddresses?: string[]
    onChange?: (addresses: string[]) => void
}

export const AddressesSection: React.FC<AddressesSectionProps> = ({
                                                                      initialAddresses = [],
                                                                      onChange
                                                                  }) => {
    const [addresses, setAddresses] = useState<AddressItem[]>(
        initialAddresses.map((addr, index) => ({key: `addr-${index}-${Date.now()}`, address: addr}))
    )
    const [bulkInput, setBulkInput] = useState('')

    // Массовое добавление адресов
    const handleAddBulk = () => {
        if (!bulkInput.trim()) return
        const newAddressesFromBulk = bulkInput
            .split('\n')
            .map(line => line.trim())
            .filter(line => line.length > 0)
            .map(line => ({key: `addr-${Date.now()}-${Math.random()}`, address: line}))
        const newAddresses = [...addresses, ...newAddressesFromBulk]
        setAddresses(newAddresses)
        setBulkInput('')
        onChange?.(newAddresses.map(a => a.address))
    }

    //Удаление адреса
    const handleRemove = (key: string) => {
        const newAddresses = addresses.filter(a => a.key !== key)
        setAddresses(newAddresses)
        onChange?.(newAddresses.map(a => a.address))
    }
    const columns: ColumnsType<AddressItem> = [
        {
            title: 'Адрес',
            dataIndex: 'address',
            key: 'address',
            width: 500,
            render: (text: string) => <Text>{text}</Text>
        },
        {
            title: 'Действия',
            key: 'actions',
            width: 150,
            align: 'right',
            render: (_, record) => (
                <Space>
                    <Button size="small">Рекламная ставка</Button>
                    <Button size="small" danger icon={<DeleteOutlined/>}
                            onClick={() => handleRemove(record.key)}></Button>
                </Space>
            )
        }
    ]
    return (
        <Card title="📍 Адреса" style={{marginBottom: '16px'}}>
            <Space direction="vertical" style={{width: '100%'}} size="medium">

                {/* Массовое добавление */}
                <div>
                    <TextArea
                        rows={3}
                        placeholder="Массовое добавление (каждый адрес с новой строки)"
                        value={bulkInput}
                        onChange={(e) => setBulkInput(e.target.value)}
                    />
                    <Button
                        type="default"
                        icon={<PlusOutlined/>}
                        onClick={handleAddBulk}
                        disabled={!bulkInput.trim()}
                        style={{marginTop: '8px'}}
                    >
                    Добавить все адреса
                    </Button>
                </div>
                {/* Таблица адресов */}
                {addresses.length > 0 && (
                    <Table
                        columns={columns}
                        dataSource={addresses}
                        pagination={false}
                        size="small"
                        scroll={{ y: 300}}
                        style={{ marginTop: '30px'}}
                    />
                )}
            </Space>
        </Card>
    )
}