import removeMd from 'remove-markdown';

/**
 * Convert Markdown to plain text
 * Uses remove-markdown library for proper Markdown parsing
 */
export function markdownToPlainText(markdown: string): string {
  if (!markdown) return '';

  return removeMd(markdown, {
    gfm: true,
    useImgAltText: true,
    stripListLeaders: true,
  });
}
