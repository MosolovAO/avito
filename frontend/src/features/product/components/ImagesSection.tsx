import React, {useState, useCallback, useRef, useEffect} from 'react'
import {Button, Space, Card, Divider, Row, Col, message} from 'antd'
import {MinusOutlined, UploadOutlined} from '@ant-design/icons'


interface ImagesSectionProps {
    initialMainImages?: File[]
    initialAdditionalImages?: File[]
    onMainImagesChange?: (files: File[]) => void
    onAdditionalImagesChange?: (files: File[]) => void
}

const MAX_FILES = 10
const MAX_FILE_SIZE = 2 * 1024 * 1024 // 2MB
const ALLOWED_TYPES = ['image/jpeg', 'image/png']

/**
 * Проверка файла на валидность
 */

const validateFile = (file: File): { valid: boolean, error?: string } => {
    if (!ALLOWED_TYPES.includes(file.type)) {
        return {
            valid: false,
            error: 'Можно загружать только JPEG или PNG изображения',

        }
    }

    if (file.size > MAX_FILE_SIZE) {
        return {
            valid: false,
            error: 'Размер файла не должен превышать 2MB',
        }
    }

    return {valid: true}
}

interface FilePreview {
    file: File
    url: string
    id: string // FIX: стабильный ключ
}

interface ImageUploadZoneProps {
    title: string
    items: FilePreview[]
    setItems: React.Dispatch<React.SetStateAction<FilePreview[]>>
    onFilesChange: (files: File[]) => void
}


const ImageUploadZone: React.FC<ImageUploadZoneProps> = ({
                                                             title,
                                                             items,
                                                             setItems,
                                                             onFilesChange,
                                                         }) => {
    const [dragOver, setDragOver] = useState(false)
    const fileInputRef = useRef<HTMLInputElement>(null)

    const prevCountRef = useRef(items.length)

    // Вызывать onFilesChange только когда items изменился
    useEffect(() => {
        if (prevCountRef.current !== items.length) {
            onFilesChange(items.map(i => i.file))
            prevCountRef.current = items.length
        }
    }, [items]);

    // При размонтировании отзываем все URL
    useEffect(() => {
        return () => {
            items.forEach(({url}) => URL.revokeObjectURL(url))
        }
    }, [items])

    // Обработка новых файлов
    const handleFiles = useCallback(
        (newFiles: File[]) => {
            const newItems: FilePreview[] = []

            for (const file of newFiles) {

                const validation = validateFile(file)

                if (!validation.valid) {
                    message.error(validation.error)
                    continue
                }

                // Создаём URL синхронно — до setState
                newItems.push({
                    file,
                    url: URL.createObjectURL(file),
                    id: generateFileId(file)
                })

            }

            setItems(prev => {

                // ← Показываем warning только если превысили лимит
                if (prev.length >= MAX_FILES) {
                    message.warning(`Максимум ${MAX_FILES} изображений`)
                    return prev
                }

                if (prev.length + newItems.length >= MAX_FILES) {
                    const allowed = newItems.slice(0, MAX_FILES - prev.length)
                    return [...prev, ...allowed]
                }
                return [...prev, ...newItems]

            })

        },
        [setItems]
    )


    // Обработка drop события
    const handleDrop = useCallback(
        (e: React.DragEvent) => {
            e.preventDefault()
            setDragOver(false)

            const droppedFiles = Array.from(e.dataTransfer.files).filter((file) => file.type.startsWith('image/'))

            if (droppedFiles.length === 0) {
                message.warning('Перетащите изображения для загрузки')
                return
            }

            handleFiles(droppedFiles)
        },
        [handleFiles]
    )

    // Обработка выбора файлов через input
    const handleFileSelect = useCallback(
        (e: React.ChangeEvent<HTMLInputElement>) => {
            const selectedFiles = Array.from(e.target.files || []).filter((file) => file.type.startsWith('image/'))

            if (selectedFiles.length === 0) {
                return
            }

            handleFiles(selectedFiles)

            // Сбрасываем value для возможности повторной загрузки того же файла
            if (fileInputRef.current) {
                fileInputRef.current.value = ''
            }
        },
        [handleFiles]
    )

    // Удаление изображения
    const handleRemove = useCallback(
        (itemToRemove: FilePreview) => {
            // Отзываем URL удаляемого файла сразу
            URL.revokeObjectURL(itemToRemove.url)
            setItems(prev => prev.filter(i => i !== itemToRemove))
        },
        [setItems, onFilesChange]
    )

    return (
        <div>
            <Divider orientation="horizontal">{title}</Divider>

            {/*Зона Drag and Drop*/}
            <div
                onDragOver={(e) => {
                    e.preventDefault()
                    setDragOver(true)
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
                style={{
                    border: `2px dashed ${dragOver ? '#1890ff' : '#d9d9d9'}`,
                    borderRadius: '8px',
                    padding: '24px',
                    textAlign: 'center',
                    backgroundColor: dragOver ? '#e6f7ff' : '#fafafa',
                    transition: 'all 0.3s',
                    marginBottom: '16px',
                    cursor: 'pointer',

                }}
            >
                <UploadOutlined
                    style={{fontSize: '48px', color: dragOver ? '#1890ff' : '#bfbfbf'}}
                />
                <p style={{margin: '8px 0 0', color: '#666'}}>
                    Перетащите изображения сюда или кликните для выбора
                </p>
                <p style={{margin: '4px 0 0', fontSize: '12px', color: '#999'}}>
                    Макс. размер: 2MB | Форматы: JPEG, PNG
                </p>

                {/*Скрытый инпут*/}

                <input
                    type='file'
                    accept="image/jpeg,image/png"
                    multiple
                    onChange={handleFileSelect}
                    style={{display: 'none'}}
                    ref={fileInputRef}
                />
            </div>
            {/*Превью изображений*/}

            {items.length > 0 && (
                <Space wrap size='small'>
                    {items.map(item => (
                        <div
                            key={item.id}
                            style={{
                                position: 'relative',
                                width: '100px',
                                height: '100px',
                                border: '1px solid #d9d9d9',
                                borderRadius: '4px',
                                overflow: 'hidden',
                            }}
                        >
                            <img
                                src={item.url}
                                alt="Preview"
                                style={{
                                    width: '100%',
                                    height: '100%',
                                    objectFit: 'cover',
                                }}
                            />

                            {/* Кнопка удаления */}
                            <Button
                                danger
                                size="small"
                                icon={<MinusOutlined/>}
                                onClick={e => {
                                    e.stopPropagation()
                                    handleRemove(item)
                                }}
                                style={{
                                    position: 'absolute',
                                    top: '4px',
                                    right: '4px',
                                    borderRadius: '50%',
                                    width: '24px',
                                    height: '24px',
                                    padding: 0,
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                }}
                            />
                        </div>
                    ))}
                </Space>
            )}
        </div>
    )
}

/**
 * Вспомогательная функция: оборачивает начальные File[] в FilePreview[].
 * URL создаётся один раз при инициализации компонента.
 */
const toPreviewItems = (files: File[]): FilePreview[] =>
    files.map(file => ({
        file,
        url: URL.createObjectURL(file),
        id: generateFileId(file)
    }))

const generateFileId = (file: File): string => {
    // Простой hash без специальных символов
    const safeName = file.name.replace(/[^a-zA-Z0-9]/g, '')
    return `${safeName}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2)}`
}


/**
 * Основной компонент ImagesSection
 */

export const ImagesSection: React.FC<ImagesSectionProps> = ({
                                                                initialMainImages = [],
                                                                initialAdditionalImages = [],
                                                                onMainImagesChange,
                                                                onAdditionalImagesChange,
                                                            }) => {
    const [mainItems, setMainItems] = useState<FilePreview[]>(() =>
        toPreviewItems(initialMainImages)
    )
    const [additionalItems, setAdditionalItems] = useState<FilePreview[]>(() =>
        toPreviewItems(initialAdditionalImages)
    )

    return (
        <Card title="🖼️ Изображения" style={{marginBottom: '16px'}}>
            <Row gutter={16}>
                {/* Колонка основных изображений */}
                <Col xs={24} lg={12}>
                    <ImageUploadZone
                        title=" Основные изображения"
                        items={mainItems}
                        setItems={setMainItems}
                        onFilesChange={onMainImagesChange || (() => {
                        })}
                    />
                </Col>

                {/* Колонка дополнительных изображений */}
                <Col xs={24} lg={12}>
                    <ImageUploadZone
                        title=" Дополнительные изображения"
                        items={additionalItems}
                        setItems={setAdditionalItems}
                        onFilesChange={onAdditionalImagesChange || (() => {
                        })}
                    />
                </Col>
            </Row>
        </Card>
    )
}
