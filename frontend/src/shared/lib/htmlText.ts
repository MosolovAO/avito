const HTML_TAG_REGEXP = /<[^>]*>/g;

export const countCharsWithoutHtml = (html: string): number =>
    html.replace(HTML_TAG_REGEXP, "").trim().length;

export const hasTextContent = (html: string | undefined): boolean =>
    countCharsWithoutHtml(html ?? "") > 0;
