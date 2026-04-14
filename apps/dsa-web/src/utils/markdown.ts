import removeMd from 'remove-markdown';

/**
 * Convert Markdown to plain text
 * Uses remove-markdown library for proper Markdown parsing
 */
export function markdownToPlainText(markdown: string): string {
  if (!markdown) return '';

  const plainText = removeMd(markdown, {
    gfm: true,
    useImgAltText: true,
    stripListLeaders: true,
  });

  // Additional post-processing to remove GFM table separator lines (e.g. |---|)
  // that remove-markdown sometimes leaves behind.
  return plainText
    .replace(/\n\|?[\s|:-]+\|?\s*(?=\n|$)/g, '\n')
    .trim();
}
