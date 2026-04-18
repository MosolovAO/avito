import React, {useState} from 'react'
import {Button, Space, Card, Tabs} from 'antd'
import {PlusOutlined, DeleteOutlined} from '@ant-design/icons'
import { RichTextEditor } from '../../../../shared/RichTextEditor'


interface DescriptionsSectionProps {
    initialDescriptions?: string[]
    onChange?: (descriptions: Record<string, string>) => void
}


export const DescriptionsSectionOld: React.FC<DescriptionsSectionProps> = ({
                                                                            initialDescriptions = {'Описание 1': ''},
                                                                            onChange,

                                                                        }) => {

    const [descriptions, setDescriptions] = useState<string[]>(initialDescriptions)
    const [activeKey, setActiveKey] = useState<string>(Object.keys(initialDescriptions)[0] || 'Описание 1')
    // Добавление описания
    const handleAdd = () => {
        const newKey = getNewKey()
        const newDescription = {...descriptions, [newKey]: ''}
        setDescriptions(newDescription)
        onChange?.(newDescription)
        setActiveKey(newKey)
    }

    // Удаление описания
    const handleDelete = (key: string) => {
        if (Object.keys(descriptions).length > 1) {
            const newDescriptions = {...descriptions}
            delete newDescriptions[key]
            setDescriptions(newDescriptions)
            onChange?.(newDescriptions)

            const remainingKeys = Object.keys(newDescriptions)
            if (key === activeKey && remainingKeys.length > 0) {
                setActiveKey(remainingKeys[0])
            }

        }
    }

    // Обновление описания
    const handleUpdate = (key: string, value: string) => {
        const newDescriptions = {...descriptions, [key]: value}
        setDescriptions(newDescriptions)
        onChange?.(newDescriptions)
    }

    const getNewKey = () => {
        const count = Object.keys(descriptions).length + 1
        return `Описание ${count}`
    }

    const tabItems = Object.entries(descriptions).map(([key, content], index) => ({
        key,
        label: `Описание ${index + 1}`,
        children: (
            <div>
                <Space style={{width: '100%', marginBottom: '12px'}}>
                    <input
                        type="text"
                        value={key}
                        disabled
                        style={{
                            flex: 1,
                            padding: '8px 12px',
                            border: '1px solid #d9d9d9',
                            borderRadius: '6px',
                            backgroundColor: '#f5f5f5',
                        }}
                    />
                    {Object.keys(descriptions).length > 1 && (
                        <Button
                            danger
                            icon={<DeleteOutlined/>}
                            onClick={() => handleDelete(key)}
                        />
                    )}
                </Space>
                <RichTextEditor
                    content={content}
                    onChange={(value) => handleUpdate(key, value)}
                    placeholder="Введите описание"
                />
            </div>
        )
    }))

    return (
        <Card title="📄 Описания" style={{marginBottom: '16px'}}>
            <Tabs
                activeKey={activeKey}
                onChange={setActiveKey}
                items={tabItems}
            />
            <Button
                type="default"
                icon={<PlusOutlined/>}
                onClick={handleAdd}
                block
                style={{marginTop: 16}}
            >
                Добавить описание
            </Button>

        </Card>
    )
}