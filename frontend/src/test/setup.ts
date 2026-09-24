import "@testing-library/jest-dom/vitest";
import {cleanup} from "@testing-library/react";
import {afterEach} from "vitest";

afterEach(() => {
    cleanup();
});

class ResizeObserverMock implements ResizeObserver {
    observe(): void {
    }

    unobserve(): void {
    }

    disconnect(): void {
    }
}

Object.defineProperty(
    globalThis,
    "ResizeObserver",
    {
        configurable: true,
        writable: true,
        value: ResizeObserverMock,
    },
);

const matchMedia = (query: string): MediaQueryList => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
});

Object.defineProperty(
    window,
    "matchMedia",
    {
        configurable: true,
        writable: true,
        value: matchMedia,
    },
);

const nativeGetComputedStyle = window.getComputedStyle.bind(window);

Object.defineProperty(
    window,
    "getComputedStyle",
    {
        configurable: true,
        writable: true,
        value: (element: Element) => nativeGetComputedStyle(element),
    },
);
