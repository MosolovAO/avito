// src/features/product/components/TitlesSection.tsx
import React, {useState} from 'react'
import {Card, Form, Input, message, Tag} from 'antd'
import type {ProductFormValues} from '../lib/productFormMapper'

const EMPTY_TITLES: string[] = []

export const TitlesSection: React.FC = () => {
    const form = Form.useFormInstance<ProductFormValues>()
    const watchedTitles = Form.useWatch('titles', {form, preserve: true})
    const titles = watchedTitles ?? EMPTY_TITLES

    const [inputValue, setInputValue] = useState('')

    const handleAddTitle = () => {
        const title = inputValue.trim()

        if (!title) {
            return
        }

        if (titles.includes(title)) {
            message.warning(`Заголовок "${title}" уже существует`)
            return
        }

        form.setFieldValue('titles', [...titles, title])
        setInputValue('')
    }

    const handleRemoveTitle = (removedTitle: string) => {
        form.setFieldValue(
            'titles',
            titles.filter((title) => title !== removedTitle)
        )
    }

    return (
        <Card title="📝 Заголовки" style={{marginBottom: 16}}>
            <Input
                value={inputValue}
                placeholder="Введите заголовок и нажмите Enter"
                onChange={(event) => setInputValue(event.target.value)}
                onPressEnter={(event) => {
                    event.preventDefault()
                    handleAddTitle()
                }}
                style={{marginBottom: 12}}
            />

            <div
                style={{
                    minHeight: 100,
                    padding: 8,
                    border: '1px solid #d9d9d9',
                    borderRadius: 6,
                    backgroundColor: '#fafafa',
                }}
            >
                {titles.length === 0 ? (
                    <span style={{color: '#999'}}>Заголовки не добавлены</span>
                ) : (
                    <div style={{display: 'flex', flexWrap: 'wrap', gap: 8}}>
                        {titles.map((title) => (
                            <Tag
                                key={title}
                                closable
                                color="blue"
                                onClose={() => handleRemoveTitle(title)}
                            >
                                {title}
                            </Tag>
                        ))}
                    </div>
                )}
            </div>

            {titles.length > 0 && (
                <div style={{marginTop: 8, color: '#999', fontSize: 12}}>
                    Всего заголовков: {titles.length}
                </div>
            )}
        </Card>
    )
}
