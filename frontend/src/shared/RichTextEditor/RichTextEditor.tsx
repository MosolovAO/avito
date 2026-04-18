import React, {useEffect, useState} from "react";
import {EditorContent, useEditor} from "@tiptap/react";
import {CodeOutlined, EyeOutlined} from '@ant-design/icons'
import {Button} from "antd";
import StarterKit from "@tiptap/starter-kit";
import Underline from "@tiptap/extension-underline";
import TextAlign from "@tiptap/extension-text-align";
import Link from "@tiptap/extension-link";
import Placeholder from "@tiptap/extension-placeholder";

import styles from "./RichTextEditor.module.css";

interface RichTextEditorProps {
    content: string
    onChange: (content: string) => void
    placeholder: string

}

interface EditorToolbarProps {
    editor: ReturnType<typeof useEditor> | null
    showHtml: boolean
    onToggleHtml: () => void
}


// Компонент Toolbar для редактора
const EditorToolbar: React.FC<EditorToolbarProps> = ({editor, showHtml, onToggleHtml}) => {
    if (!editor) return null

    return (
        <div style={{
            borderBottom: '1px solid #d9d9d9',
            padding: '8px',
            backgroundColor: '#fafafa',
            display: 'flex',
            gap: '4px',
            flexWrap: 'wrap'
        }}
        >
            <Button
                size="small"
                type={editor.isActive('bold') ? 'primary' : 'default'}
                onClick={() => editor.chain().focus().toggleBold().run()}
                disabled={!editor.can().chain().focus().toggleBold().run()}
            >
                B
            </Button>
            <Button
                size="small"
                type={editor.isActive('italic') ? 'primary' : 'default'}
                onClick={() => editor.chain().focus().toggleItalic().run()}
                disabled={!editor.can().chain().focus().toggleItalic().run()}
            >
                I
            </Button>
            <Button
                size="small"
                type={editor.isActive('underline') ? 'primary' : 'default'}
                onClick={() => editor.chain().focus().toggleUnderline().run()}
                disabled={!editor.can().chain().focus().toggleUnderline().run()}
            >
                U
            </Button>
            <Button
                size="small"
                type={editor.isActive('strike') ? 'primary' : 'default'}
                onClick={() => editor.chain().focus().toggleStrike().run()}
                disabled={!editor.can().chain().focus().toggleStrike().run()}
            >
                S
            </Button>
            <Button
                size="small"
                type={editor.isActive('bulletList') ? 'primary' : 'default'}
                onClick={() => editor.chain().focus().toggleBulletList().run()}
            >
                • Список
            </Button>
            <Button
                size="small"
                type={editor.isActive('orderedList') ? 'primary' : 'default'}
                onClick={() => editor.chain().focus().toggleOrderedList().run()}
            >
                1. Список
            </Button>
            <Button
                size="small"
                type={editor.isActive({textAlign: 'left'}) ? 'primary' : 'default'}
                onClick={() => editor.chain().focus().setTextAlign('left').run()}
            >
                ←
            </Button>
            <Button
                size="small"
                type={editor.isActive({textAlign: 'center'}) ? 'primary' : 'default'}
                onClick={() => editor.chain().focus().setTextAlign('center').run()}
            >
                ↔
            </Button>
            <Button
                size="small"
                type={editor.isActive({textAlign: 'right'}) ? 'primary' : 'default'}
                onClick={() => editor.chain().focus().setTextAlign('right').run()}
            >
                →
            </Button>
            <div className={styles.toolbarDivider}/>
            <Button
                size="small"
                icon={showHtml ? <EyeOutlined/> : <CodeOutlined/>}
                onClick={onToggleHtml}
                className={styles.toolbarButton}
            >
                {showHtml ? 'Визуально' : 'HTML'}
            </Button>
        </div>
    )
}

export const RichTextEditor: React.FC<RichTextEditorProps> = ({content, onChange, placeholder = 'Введите описание...//' }) => {
    const [showHtml, setShowHtml] = useState(false)

    const editor = useEditor({
        extensions: [
            StarterKit,
            Underline,
            TextAlign.configure({types: ['heading', 'paragraph']}),
            Link.configure({openOnClick: false}),
            Placeholder.configure({  // <-- Добавь это
                placeholder: placeholder,
            }),

        ],
        content,
        onUpdate: ({editor}) => {
            onChange(editor.getHTML())
        },
        // Добавляем атрибуты напрямую на ProseMirror-элемент
        editorProps: {
            attributes: {
                spellcheck: 'true',
                class: styles.proseMirror,
            },
        },
        immediatelyRender: false,
        autofocus: false,

    })

    useEffect(() => {
        if (editor && !showHtml) {
            const currentContent = editor.getHTML()
            if (currentContent !== content) {
                editor.commands.setContent(content)
            }
        }
    }, [content, showHtml, editor])

    const handleToggleHtml = () => {
        setShowHtml(!showHtml)
    }

    const handleHtmlChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
        onChange(e.target.value)
    }


    return (
        <div className={styles.editorWrapper}>
            <EditorToolbar editor={editor} showHtml={showHtml}
                           onToggleHtml={handleToggleHtml}
            />

            {showHtml ? (
                <textarea
                    className={styles.htmlTextarea}
                    value={content}
                    onChange={handleHtmlChange}
                    spellCheck={false}
                />
            ) : (
                <>
                    <EditorContent editor={editor} className={styles.editorContent}/>
                </>
            )}

        </div>
    )
}

