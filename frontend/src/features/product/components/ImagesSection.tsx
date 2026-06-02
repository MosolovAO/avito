// src/features/product/components/ImagesSection.tsx
import React, {useEffect, useRef, useState} from 'react'
import {Button, Card, Col, Divider, Form, message, Row, Space} from 'antd'
import {MinusOutlined, UploadOutlined} from '@ant-design/icons'
import type {ProductImageAssetValue, ProductImageValue} from '../../../entities/product/types'
import type {ProductFormValues} from '../lib/productFormMapper'

type ImageFieldName = 'main_images' | 'additional_images'

interface ImageUploadZoneProps {
    title: string
    name: ImageFieldName
}

interface FilePreview {
    source: ProductImageValue
    url: string
    id: string
    revokeUrl: boolean
}

const MAX_FILES = 200
const MAX_FILE_SIZE = 2 * 1024 * 1024
const ALLOWED_TYPES = ['image/jpeg', 'image/png']
const FILE_ID_UNSAFE_CHARS_REGEXP = /[^a-zA-Z0-9]/g
const EMPTY_IMAGES: ProductImageValue[] = []

const isFile = (value: ProductImageValue): value is File => value instanceof File

const validateFile = (file: File): string | null => {
    if (!ALLOWED_TYPES.includes(file.type)) {
        return 'Можно загружать только JPEG или PNG изображения'
    }

    if (file.size > MAX_FILE_SIZE) {
        return 'Размер файла не должен превышать 2MB'
    }

    return null
}

const isImageAsset = (value: ProductImageValue): value is ProductImageAssetValue =>
    typeof value === 'object' && value !== null && 'id' in value && 'url' in value

const getImageUrl = (image: ProductImageValue): string => {
    if (isFile(image)) {
        return URL.createObjectURL(image)
    }

    if (isImageAsset(image)) {
        return image.url
    }

    return image
}


const getImageFiles = (files: FileList | null): File[] =>
    Array.from(files ?? []).filter((file) => file.type.startsWith('image/'))

const getPreviewId = (image: ProductImageValue, index: number): string => {
    if (isImageAsset(image)) {
        return `asset-${image.id}-${index}`
    }

    if (!isFile(image)) {
        return `remote-${index}-${image}`
    }

    const safeName = image.name.replace(FILE_ID_UNSAFE_CHARS_REGEXP, '') || 'file'
    return `file-${index}-${safeName}-${image.size}-${image.lastModified}`
}

const createPreview = (image: ProductImageValue, index: number): FilePreview => {
    if (!isFile(image)) {
        return {
            source: image,
            url: getImageUrl(image),
            id: getPreviewId(image, index),
            revokeUrl: false,
        }
    }

    return {
        source: image,
        url: getImageUrl(image),
        id: getPreviewId(image, index),
        revokeUrl: true,
    }
}

const revokePreviewUrl = (preview: FilePreview): void => {
    if (preview.revokeUrl) {
        URL.revokeObjectURL(preview.url)
    }
}


const ImageUploadZone: React.FC<ImageUploadZoneProps> = ({title, name}) => {
    const form = Form.useFormInstance<ProductFormValues>()
    const watchedImages = Form.useWatch(name, {form, preserve: true})
    const images = watchedImages ?? EMPTY_IMAGES

    const [dragOver, setDragOver] = useState(false)
    const [previews, setPreviews] = useState<FilePreview[]>([])
    const fileInputRef = useRef<HTMLInputElement>(null)

    useEffect(() => {
        const nextPreviews = images.map(createPreview)

        setPreviews(nextPreviews)

        return () => {
            nextPreviews.forEach(revokePreviewUrl)
        }
    }, [images])

    const updateImages = (nextImages: ProductImageValue[]) => {
        form.setFieldValue(name, nextImages)
    }

    const handleFiles = (newFiles: File[]) => {
        const availableSlots = MAX_FILES - images.length

        if (availableSlots <= 0) {
            message.warning(`Максимум ${MAX_FILES} изображений`)
            return
        }

        const acceptedFiles: File[] = []

        for (const file of newFiles) {
            if (acceptedFiles.length >= availableSlots) {
                break
            }

            const validationError = validateFile(file)

            if (validationError) {
                message.error(validationError)
                continue
            }

            acceptedFiles.push(file)
        }

        if (newFiles.length > availableSlots) {
            message.warning(`Максимум ${MAX_FILES} изображений`)
        }

        if (acceptedFiles.length === 0) {
            return
        }

        updateImages([...images, ...acceptedFiles])
    }

    const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
        event.preventDefault()
        setDragOver(false)

        const droppedFiles = getImageFiles(event.dataTransfer.files)

        if (droppedFiles.length === 0) {
            message.warning('Перетащите изображения для загрузки')
            return
        }

        handleFiles(droppedFiles)
    }

    const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
        const selectedFiles = getImageFiles(event.target.files)

        if (selectedFiles.length > 0) {
            handleFiles(selectedFiles)
        }

        event.target.value = ''
    }

    const handleRemove = (indexToRemove: number) => {
        updateImages(images.filter((_, index) => index !== indexToRemove))
    }

    return (
        <div>
            <Divider orientation="horizontal">{title}</Divider>

            <div
                onDragOver={(event) => {
                    event.preventDefault()
                    setDragOver(true)
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
                style={{
                    border: `2px dashed ${dragOver ? '#1890ff' : '#d9d9d9'}`,
                    borderRadius: 8,
                    padding: 24,
                    textAlign: 'center',
                    backgroundColor: dragOver ? '#e6f7ff' : '#fafafa',
                    transition: 'all 0.3s',
                    marginBottom: 16,
                    cursor: 'pointer',
                }}
            >
                <UploadOutlined
                    style={{
                        fontSize: 48,
                        color: dragOver ? '#1890ff' : '#bfbfbf',
                    }}
                />

                <p style={{margin: '8px 0 0', color: '#666'}}>
                    Перетащите изображения сюда или кликните для выбора
                </p>

                <p style={{margin: '4px 0 0', fontSize: 12, color: '#999'}}>
                    Макс. размер: 2MB | Форматы: JPEG, PNG
                </p>

                <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/jpeg,image/png"
                    multiple
                    onChange={handleFileSelect}
                    style={{display: 'none'}}
                />
            </div>

            {previews.length > 0 && (
                <Space wrap size="small">
                    {previews.map((preview, index) => (
                        <div
                            key={preview.id}
                            style={{
                                position: 'relative',
                                width: 100,
                                height: 100,
                                border: '1px solid #d9d9d9',
                                borderRadius: 4,
                                overflow: 'hidden',
                            }}
                        >
                            <img
                                src={preview.url}
                                alt="Preview"
                                style={{
                                    width: '100%',
                                    height: '100%',
                                    objectFit: 'cover',
                                }}
                            />

                            <Button
                                danger
                                size="small"
                                icon={<MinusOutlined/>}
                                onClick={(event) => {
                                    event.stopPropagation()
                                    handleRemove(index)
                                }}
                                style={{
                                    position: 'absolute',
                                    top: 4,
                                    right: 4,
                                    borderRadius: '50%',
                                    width: 24,
                                    height: 24,
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

export const ImagesSection: React.FC = () => {
    return (
        <Card title="🖼️ Изображения" style={{marginBottom: 16}}>
            <Row gutter={16}>
                <Col xs={24} lg={12}>
                    <ImageUploadZone title="Основные изображения" name="main_images"/>
                </Col>

                <Col xs={24} lg={12}>
                    <ImageUploadZone title="Дополнительные изображения" name="additional_images"/>
                </Col>
            </Row>
        </Card>
    )
}
