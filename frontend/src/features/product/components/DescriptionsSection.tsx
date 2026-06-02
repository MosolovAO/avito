// src/features/product/components/DescriptionsSection.tsx
import React, {useId, useState} from 'react'
import {Card, Form, Tabs} from 'antd'
import type {TabsProps} from 'antd'
import {RichTextEditor} from '../../../shared/RichTextEditor'
import type {ProductFormValues} from '../lib/productFormMapper'
import {countCharsWithoutHtml} from '../../../shared/lib/htmlText'

type TargetKey = React.MouseEvent | React.KeyboardEvent | string

const EMPTY_DESCRIPTIONS: string[] = ['']

export const DescriptionsSection: React.FC = () => {
    const form = Form.useFormInstance<ProductFormValues>()
    const watchedDescriptions = Form.useWatch('descriptions', {form, preserve: true})
    const descriptions = watchedDescriptions ?? EMPTY_DESCRIPTIONS

    const tabsId = useId()
    const descriptionKeys = descriptions.map((_, index) => `${tabsId}-${index}`)
    const [activeIndex, setActiveIndex] = useState(0)
    const resolvedActiveIndex = descriptions.length > 0
        ? Math.min(activeIndex, descriptions.length - 1)
        : 0
    const resolvedActiveKey = descriptionKeys[resolvedActiveIndex]

    const setDescriptions = (nextDescriptions: string[]) => {
        form.setFieldValue('descriptions', nextDescriptions.length > 0 ? nextDescriptions : [''])
    }

    const handleAdd = () => {
        setDescriptions([...descriptions, ''])
        setActiveIndex(descriptions.length)
    }

    const handleDelete = (targetKey: TargetKey) => {
        if (typeof targetKey !== 'string' || descriptions.length <= 1) {
            return
        }

        const index = descriptionKeys.indexOf(targetKey)

        if (index === -1) {
            return
        }

        const nextDescriptions = descriptions.filter((_, currentIndex) => currentIndex !== index)

        setDescriptions(nextDescriptions)

        if (index < resolvedActiveIndex) {
            setActiveIndex(resolvedActiveIndex - 1)
            return
        }

        if (index === resolvedActiveIndex) {
            setActiveIndex(Math.max(0, Math.min(index, nextDescriptions.length - 1)))
        }
    }

    const handleUpdate = (index: number, value: string) => {
        const nextDescriptions = [...descriptions]
        nextDescriptions[index] = value

        setDescriptions(nextDescriptions)
    }

    const items: TabsProps['items'] = descriptions.map((content, index) => ({
        key: descriptionKeys[index] ?? String(index),
        label: `Описание ${index + 1}`,
        children: (
            <div>
                <RichTextEditor
                    content={content}
                    onChange={(value) => handleUpdate(index, value)}
                    placeholder="Введите описание..."
                />

                <span style={{marginTop: 10, display: 'block'}}>
                    Всего символов: {countCharsWithoutHtml(content)}
                </span>
            </div>
        ),
    }))

    return (
        <Card title="📄 Описания" style={{marginBottom: 16}}>
            <Tabs
                type="editable-card"
                activeKey={resolvedActiveKey}
                onChange={(nextKey) => {
                    const nextIndex = descriptionKeys.indexOf(nextKey)

                    if (nextIndex !== -1) {
                        setActiveIndex(nextIndex)
                    }
                }}
                animated={{inkBar: true, tabPane: false}}
                destroyOnHidden={false}
                items={items}
                onEdit={(targetKey, action) => {
                    if (action === 'add') {
                        handleAdd()
                        return
                    }

                    handleDelete(targetKey)
                }}
            />
        </Card>
    )
}
