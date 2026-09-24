import {defineConfig} from "vitest/config";
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
    plugins: [react()],

    test: {
        environment: "jsdom",
        setupFiles: "./src/test/setup.ts",
        css: true,
        maxWorkers: 1,
    },

    server: {
        port: 3000,
        host: true,
        proxy: {
            '/api': {
                target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000',
                changeOrigin: true,
            },
        },
    },

})
