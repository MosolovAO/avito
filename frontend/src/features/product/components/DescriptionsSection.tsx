import React, {useState} from 'react'
import {Card, Tabs} from 'antd'
import type {TabsProps} from "antd";
import {RichTextEditor} from '../../../shared/RichTextEditor'


interface DescriptionsSectionProps {
    initialDescriptions?: string[]
    onChange?: (descriptions: string[]) => void
}

type TargetKey = React.MouseEvent | React.KeyboardEvent | string

// Утилита для подсчёта символов без HTML-тегов
const countCharsWithoutHtml = (html: string): number => {
    return html.replace(/<[^>]*>/g, '').trim().length
}

export const DescriptionsSection: React.FC<DescriptionsSectionProps> = ({
                                                                            initialDescriptions = [''],
                                                                            onChange,

                                                                        }) => {

    const [descriptions, setDescriptions] = useState<string[]>(initialDescriptions)
    const [activeKey, setActiveKey] = useState<string>('0')

    // Добавление описания
    const handleAdd = () => {
        const newDescription = [...descriptions, '']
        setDescriptions(newDescription)
        onChange?.(newDescription)
        setActiveKey(String(descriptions.length))
    }

    // Удаление описания
    const handleDelete = (targetKey: TargetKey) => {
        // targetKey приходит как строка-индекс (например, '1')
        const index = Number(targetKey);
        if (descriptions.length <= 1) return; // нельзя удалить последнюю вкладку

        const newDescriptions = descriptions.filter((_, i) => i !== index);
        setDescriptions(newDescriptions);
        onChange?.(newDescriptions);

        // Корректируем активный ключ, если удалили текущую вкладку
        if (targetKey === activeKey) {
            // Если удалили не последнюю — берём следующий элемент, иначе предыдущий
            const newActiveIndex = index >= newDescriptions.length ? index - 1 : index;
            setActiveKey(String(Math.max(0, newActiveIndex)));
        }
    };


    const onEdit = (targetKey: TargetKey, action: 'add' | 'remove') => {
        if (action === 'add') {
            handleAdd()
        } else {
            handleDelete(targetKey)
        }
    }
    // Обновление описания
    const handleUpdate = (index: number, value: string) => {
        const newDescriptions = [...descriptions]
        newDescriptions[index] = value
        setDescriptions(newDescriptions)
        onChange?.(newDescriptions)
    }


    const items: TabsProps['items'] = descriptions.map(
        (content, index) => ({
            key: String(index),
            label: `Описание ${index + 1}`,
            children: (
                <div>
                    <RichTextEditor
                        key={String(index)}
                        content={content}
                        onChange={(value) => handleUpdate(index, value)}
                        placeholder="Введите описание..."

                    />
                    <span style={{marginTop: '10px', display: 'block'}}>Всего символов: {countCharsWithoutHtml(content)}</span>
                </div>
            )
        })
    )

    return (
        <Card title="📄 Описания" style={{marginBottom: '16px'}}>
            <Tabs
                type="editable-card"
                activeKey={activeKey}
                onChange={setActiveKey}
                onEdit={onEdit}
                items={items}
                hideAdd={false}
            />

        </Card>
    )
}