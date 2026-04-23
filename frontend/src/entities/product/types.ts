// Тип Product (задача для парсинга)
export interface Product {
    id: number
    name: string
    url: string
    price: number
    listingfee: string
    email: string,
    contactphone: string,
    managername: string,
    avitostatus: string,
    companyname: string,
    contactmethod: string,
    adtype: string,
    availability: string,
    activate: boolean
    price_min: number
    price_max: number
    price_step: number
    titles: string[]
    main_images: string[]
    additional_images: string[]
    descriptions: Record<string, string>
    addresses: string[]
    category: string
    schedule: Record<string, string>
    next_update_time: string | null
    projects: { id: number; project_name: string }[]
    price_randomization_enabled: boolean

}

// Тип Product1 (созданное объявление)
export interface Product1 {
    id: number
    title: string
    urls: string[]
    description: string
    created_date: string
    task_id: number
    selected_option: Record<string, string>
    project_name: string[]
}


// Тип ProductOption
export interface ProductOption {
    id: number
    option_title: string
    option_code: string
    option_title_ru: string
    option_title_en: string
    allow_multiple: boolean
    allow_multiple_options: boolean
    categories: number[]
}

export type ProductImageValue = File | string

// Типы для формы добавления/редактирования продукта
export interface ProductFormData  {
    titles: string[]
    price_randomization_enabled: boolean
    main_images: ProductImageValue[]
    additional_images: ProductImageValue[]
    descriptions: string[]
    addresses: string[]
    category: string
    listingfee: string
    email: string
    contactphone: string
    managername: string
    avitostatus: string
    companyname: string
    contactmethod: string
    adtype: string
    availability: string
    price: number
    price_min: number
    price_max: number
    price_step: number
    projects: number[]
    options: { option_id: number; value: string }[]
    schedule: {
        frequency?: number
        days?: string[]
    }

}

/**
 * Тип изображения продукта
 */
export interface ProductImage {
    id?: string | number
    url: string
    file?: File
    isUploaded: boolean
}


/**
 * Ответ сервера после загрузки изображения
 */
export interface UploadImageResponse {
    id: string | number
    url: string
}

