import { describe, expect, it } from 'vitest';
import { markdownToPlainText } from '../markdown';

describe('markdownToPlainText', () => {
  it('removes markdown syntax from links, images, and headings', () => {
    expect(
      markdownToPlainText('![logo](https://example.com/logo.png)\n[OpenAI](https://openai.com)\n# Title')
    ).toBe('logo\nOpenAI\nTitle');
  });

  it('removes common formatting markers while keeping readable content', () => {
    expect(
      markdownToPlainText('**Bold**\n> Quote\n1. Ordered item\n- Bullet item\n`inline code`')
    ).toBe('Bold\nQuote\nOrdered item\nBullet item\ninline code');
  });

  it('preserves underscores in variable names and identifiers', () => {
    // Underscore-separated words like variable names should NOT be treated as italic
    expect(markdownToPlainText('stock_code')).toBe('stock_code');
    expect(markdownToPlainText('user_name')).toBe('user_name');
    expect(markdownToPlainText('api_key_v2')).toBe('api_key_v2');
  });

  it('handles asterisk emphasis correctly', () => {
    // Single asterisk for italic
    expect(markdownToPlainText('*italic text*')).toBe('italic text');
    // Double asterisk for bold
    expect(markdownToPlainText('**bold text**')).toBe('bold text');
    // Combined emphasis
    expect(markdownToPlainText('***bold italic***')).toBe('bold italic');
  });

  it('handles underscore emphasis correctly when used as actual Markdown', () => {
    // Underscore emphasis only works at word boundaries or with whitespace
    expect(markdownToPlainText('_italic text_')).toBe('italic text');
    expect(markdownToPlainText('__bold text__')).toBe('bold text');
  });

  it('handles fenced code blocks', () => {
    expect(
      markdownToPlainText('```python\nprint("hello")\n```')
    ).toBe('print("hello")');
    expect(
      markdownToPlainText('```\nmulti\nline\ncode\n```')
    ).toBe('multi\nline\ncode');
  });

  it('handles tables with various content', () => {
    const input = `| Header | Value |
|--------|-------|
| cell1  | cell2 |
| **bold** | *italic* |`;
    const result = markdownToPlainText(input);
    expect(result).toContain('Header');
    expect(result).toContain('Value');
    expect(result).toContain('cell1');
    expect(result).toContain('cell2');
    expect(result).toContain('bold');
    expect(result).toContain('italic');
  });

  it('handles mixed content with headings, lists, and code', () => {
    const input = `# Main Title

## Section

Some text with **bold** and *italic*.

- Item 1
- Item 2

\`\`\`js
const x = 1;
\`\`\`

More text.`;
    const result = markdownToPlainText(input);
    expect(result).toContain('Main Title');
    expect(result).toContain('Section');
    expect(result).toContain('Some text with bold and italic');
    expect(result).toContain('Item 1');
    expect(result).toContain('Item 2');
    expect(result).toContain('const x = 1');
  });

  it('handles strikethrough in GFM', () => {
    expect(markdownToPlainText('~~deleted~~')).toBe('deleted');
  });

  it('handles blockquotes', () => {
    expect(markdownToPlainText('> This is a quote')).toBe('This is a quote');
    expect(markdownToPlainText('> Multi\n> line\n> quote')).toBe('Multi\nline\nquote');
  });

  it('returns empty string for empty or null input', () => {
    expect(markdownToPlainText('')).toBe('');
    expect(markdownToPlainText(null as unknown as string)).toBe('');
  });
});
