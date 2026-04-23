import React, {useState, useCallback, useRef, useEffect} from 'react'
import {Button, Space, Card, Divider, Row, Col, message} from 'antd'
import {MinusOutlined, UploadOutlined} from '@ant-design/icons'
import type {ProductImageValue} from "../../../entities/product/types.ts";


interface ImagesSectionProps {
    initialMainImages?: ProductImageValue[]
    initialAdditionalImages?: ProductImageValue[]
    onMainImagesChange?: (files: ProductImageValue[]) => void
    onAdditionalImagesChange?: (files: ProductImageValue[]) => void
}


interface FilePreview {
    source: ProductImageValue
    url: string
    id: string // FIX: стабильный ключ
    revokeUrl: boolean
}

interface ImageUploadZoneProps {
    title: string
    items: FilePreview[]
    setItems: React.Dispatch<React.SetStateAction<FilePreview[]>>
    onFilesChange: (files: ProductImageValue[]) => void
}

const MAX_FILES = 10
const MAX_FILE_SIZE = 2 * 1024 * 1024 // 2MB
const ALLOWED_TYPES = ['image/jpeg', 'image/png']
const FILE_ID_UNSAFE_CHARS_REGEXP = /[^a-zA-Z0-9]/g

/** Проверка файла на валидность **/
const validateFile = (file: File): string | null => {
    if (!ALLOWED_TYPES.includes(file.type)) {
        return 'Можно загружать только JPEG или PNG изображения'
    }

    if (file.size > MAX_FILE_SIZE) {
        return 'Размер файла не должен превышать 2MB'
    }

    return null
}

const isFile = (value: ProductImageValue): value is File => value instanceof File

const generateFileId = (file: File): string => {
    // Простой hash без специальных символов
    const safeName = file.name.replace(FILE_ID_UNSAFE_CHARS_REGEXP, '') || 'file'
    return `${safeName}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2)}`
}

const createFilePreview = (file: File): FilePreview => ({
    source: file,
    url: URL.createObjectURL(file),
    id: generateFileId(file),
    revokeUrl: true,
})

const revokePreviewUrl = (item: FilePreview): void => {
    if (item.revokeUrl) {
        URL.revokeObjectURL(item.url)
    }
}

const getImageFiles = (files: FileList | null): File[] =>
    Array.from(files ?? []).filter((file) => file.type.startsWith('image/'))

const getPreviewSources = (items: FilePreview[]): ProductImageValue[] =>
    items.map((item) => item.source)

const toPreviewItems = (images: ProductImageValue[]): FilePreview[] =>
    images.map((image, index) => {
        if (isFile(image)) {
            return createFilePreview(image)
        }
        return {
            source: image,
            url: image,
            id: `remote-${index}-${image}`,
            revokeUrl: false,
        }
    })

const noopImagesChange = (): void => {
}

const ImageUploadZone: React.FC<ImageUploadZoneProps> = ({
                                                             title,
                                                             items,
                                                             setItems,
                                                             onFilesChange,
                                                         }) => {
    const [dragOver, setDragOver] = useState(false)
    const fileInputRef = useRef<HTMLInputElement>(null)
    const latestItemsRef = useRef(items)

    // Храним актуальный список для cleanup при размонтировании.
    useEffect(() => {
        latestItemsRef.current = items;
    }, [items])
    // Освобождаем только object URL, созданные через URL.createObjectURL().
    useEffect(() => {
        return () => {
            latestItemsRef.current.forEach(revokePreviewUrl)
        }
    }, [])

    // Единая точка изменения локального состояния и уведомления родителя.
    const commitItems = useCallback(
        (nextItems: FilePreview[]) => {
            setItems(nextItems)
            onFilesChange(getPreviewSources(nextItems))
        },
        [onFilesChange, setItems]
    )

    // Валидирует выбранные файлы, создаёт preview и добавляет их в список.
    const handleFiles = useCallback(
        (newFiles: File[]) => {
            const availableSlots = MAX_FILES - items.length

            if (availableSlots <= 0) {
                message.warning(`Максимум ${MAX_FILES} изображений`)
                return
            }

            const acceptedItems: FilePreview[] = []

            for (const file of newFiles) {
                if (acceptedItems.length >= availableSlots) {
                    break
                }

                const validationError = validateFile(file)

                if (validationError) {
                    message.error(validationError)
                    continue
                }

                acceptedItems.push(createFilePreview(file))
            }

            if (newFiles.length > availableSlots) {
                message.warning(`Максимум ${MAX_FILES} изображений`)
            }
            if (acceptedItems.length === 0) {
                return
            }
            commitItems([...items, ...acceptedItems])
        }, [commitItems, items]
    )


    // Обработка drop события
    const handleDrop = useCallback(
        (e: React.DragEvent) => {
            e.preventDefault()
            setDragOver(false)

            const droppedFiles = getImageFiles(e.dataTransfer.files)

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
            const selectedFiles = getImageFiles(e.target.files)

            if (selectedFiles.length > 0) {
                handleFiles(selectedFiles)
            }

            e.target.value = ''
        },
        [handleFiles]
    )

    // Удаление изображения
    const handleRemove = useCallback(
        (itemToRemove: FilePreview) => {
            revokePreviewUrl(itemToRemove)

            commitItems(items.filter((item) => item.id !== itemToRemove.id))
        },
        [commitItems, items]
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
                        title="Основные изображения"
                        items={mainItems}
                        setItems={setMainItems}
                        onFilesChange={onMainImagesChange ?? noopImagesChange}
                    />
                </Col>

                {/* Колонка дополнительных изображений */}
                <Col xs={24} lg={12}>
                    <ImageUploadZone
                        title="Дополнительные изображения"
                        items={additionalItems}
                        setItems={setAdditionalItems}
                        onFilesChange={onAdditionalImagesChange ?? noopImagesChange}
                    />
                </Col>
            </Row>
        </Card>
    )
}
