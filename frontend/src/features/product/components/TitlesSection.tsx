import React, {useState} from 'react'
import {Input, Card, Tag, message} from 'antd'

interface TitlesSectionProps {
    initialTitles?: string[]
    onChange?: (titles: string[]) => void
    value?: string[]

}

export const TitlesSection: React.FC<TitlesSectionProps> = ({
                                                                initialTitles = [],
                                                                onChange,
                                                            }) => {
    const [titles, setTitles] = useState<string[]>(initialTitles?.filter(t => t.trim()) || [])
    const [inputValue, setInputValue] = useState('')

    const handleAddTitle = () => {
        const trimmedValue = inputValue.trim()

        if (!trimmedValue) {
            return
        }
        if (titles.includes(trimmedValue)) {
            return message.warning(`Заголовок "${trimmedValue}" уже существует`)

        }

        const newTitles = [...titles, trimmedValue]
        setTitles(newTitles)
        onChange?.(newTitles)
        setInputValue('')

    }

    const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'Enter') {
            e.preventDefault()
            handleAddTitle()
        }
    }

    const handleRemoveTitle = (removedTitle: string) => {
        const newTitles = titles.filter((title) => title !== removedTitle)
        setTitles(newTitles)
        onChange?.(newTitles)
    }

    return (
        <Card title="📝 Заголовки" style={{marginBottom: '16px'}}>
            <Input
                value={inputValue}
                placeholder="Введите заголовок и нажмите Enter"
                onChange={(e) => setInputValue(e.target.value)}
                onKeyPress={handleKeyPress}
                style={{marginBottom: '12px'}}
            />

            {/* Область с тегами (как textarea) */}
            <div
                style={{
                    minHeight: '100px',
                    padding: '8px',
                    border: '1px solid #d9d9d9',
                    borderRadius: '6px',
                    backgroundColor: '#fafafa'
                }}
            >
                {titles.length === 0 ? (
                    <span style={{color: '#999'}}>Заголовки не добавлены </span>
                ) : (
                    <div style={{display: 'flex', flexWrap: 'wrap', gap: '8px'}}>
                        {titles.map((title) => (
                            <Tag
                                key={title}
                                closable
                                onClose={() => handleRemoveTitle(title)}
                                color="blue"
                                style={{marginBottom: '4px'}}
                            >
                                {title}
                            </Tag>
                        ))}
                    </div>
                )}
            </div>

            {/* Счётчик заголовков */}

            {titles.length > 0 && (
                <div style={{marginTop: '8px', color: '#999', fontSize: '12px'}}>
                    Всего заголовков: {titles.length}
                </div>
            )}

        </Card>
    )
}