// src/features/product/components/DescriptionsSection.tsx
import React, {useEffect, useState} from 'react'
import {Card, Form, Tabs} from 'antd'
import type {TabsProps} from 'antd'
import {RichTextEditor} from '../../../shared/RichTextEditor'
import type {ProductFormValues} from '../lib/productFormMapper'

type TargetKey = React.MouseEvent | React.KeyboardEvent | string

const EMPTY_DESCRIPTIONS: string[] = ['']

const countCharsWithoutHtml = (html: string): number =>
    html.replace(/<[^>]*>/g, '').trim().length

const createDescriptionKey = (): string =>
    `description-${Date.now()}-${Math.random().toString(36).slice(2)}`

export const DescriptionsSection: React.FC = () => {
    const form = Form.useFormInstance<ProductFormValues>()
    const watchedDescriptions = Form.useWatch('descriptions', {form, preserve: true})
    const descriptions = watchedDescriptions ?? EMPTY_DESCRIPTIONS

    const [descriptionKeys, setDescriptionKeys] = useState<string[]>(() =>
        descriptions.map(createDescriptionKey)
    )
    const [activeKey, setActiveKey] = useState(() => descriptionKeys[0] ?? createDescriptionKey())

    useEffect(() => {
        setDescriptionKeys((currentKeys) => {
            if (currentKeys.length === descriptions.length) {
                return currentKeys
            }

            if (currentKeys.length < descriptions.length) {
                const keysToAdd = Array.from(
                    {length: descriptions.length - currentKeys.length},
                    createDescriptionKey
                )

                return [...currentKeys, ...keysToAdd]
            }

            return currentKeys.slice(0, descriptions.length)
        })
    }, [descriptions.length])

    useEffect(() => {
        const firstKey = descriptionKeys[0]

        if (!firstKey) {
            return
        }

        const activeKeyExists = descriptionKeys.includes(activeKey)

        if (!activeKeyExists) {
            setActiveKey(firstKey)
        }
    }, [activeKey, descriptionKeys])

    const setDescriptions = (nextDescriptions: string[]) => {
        form.setFieldValue('descriptions', nextDescriptions.length > 0 ? nextDescriptions : [''])
    }

    const handleAdd = () => {
        const nextKey = createDescriptionKey()

        setDescriptionKeys((currentKeys) => [...currentKeys, nextKey])
        setDescriptions([...descriptions, ''])
        setActiveKey(nextKey)
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
        const nextKeys = descriptionKeys.filter((key) => key !== targetKey)

        setDescriptionKeys(nextKeys)
        setDescriptions(nextDescriptions)

        if (targetKey === activeKey) {
            const nextActiveIndex = index >= nextKeys.length ? index - 1 : index
            setActiveKey(nextKeys[Math.max(0, nextActiveIndex)] ?? nextKeys[0])
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
                activeKey={activeKey}
                onChange={setActiveKey}
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
