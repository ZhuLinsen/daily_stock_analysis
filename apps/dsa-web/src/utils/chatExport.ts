import type { UiLanguage } from '../i18n/uiText';
import { type LocalizableSkill, resolveMessageSkillLabels } from '../locales/strategyText';
import type { Message } from '../stores/agentChatStore';
import { getRuntimeInitialLanguage } from './uiLanguage';

export const MAX_CHAT_NOTIFICATION_CHARS = 50_000;

export interface ChatMarkdownFormatOptions {
  skills?: ReadonlyArray<LocalizableSkill>;
  compact?: boolean;
  omitSkillLabels?: boolean;
}

const CHAT_EXPORT_TEXT: Record<UiLanguage, {
  locale: string;
  title: string;
  generatedAt: string;
  userHeading: string;
  assistantHeading: string;
  filenamePrefix: string;
}> = {
  zh: {
    locale: 'zh-CN',
    title: '# 问股会话',
    generatedAt: '生成时间',
    userHeading: '## 用户',
    assistantHeading: '## AI',
    filenamePrefix: '问股会话',
  },
  en: {
    locale: 'en-US',
    title: '# Ask AI Session',
    generatedAt: 'Generated at',
    userHeading: '## User',
    assistantHeading: '## AI',
    filenamePrefix: 'ask-ai-session',
  },
};

function formatCompactTimestamp(now: Date): string {
  const pad = (value: number) => value.toString().padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

/**
 * Format chat messages as Markdown for export.
 */
export function formatSessionAsMarkdown(
  messages: Message[],
  language?: UiLanguage,
  options?: ChatMarkdownFormatOptions,
): string {
  const resolvedLanguage = language ?? getRuntimeInitialLanguage();
  const text = CHAT_EXPORT_TEXT[resolvedLanguage];
  const compact = Boolean(options?.compact);
  const omitSkillLabels = Boolean(options?.omitSkillLabels);
  const now = new Date();
  const headerTitle = compact && resolvedLanguage === 'en' ? '# Chat' : text.title;
  const headerMeta = compact && resolvedLanguage === 'en'
    ? formatCompactTimestamp(now)
    : `${text.generatedAt}: ${now.toLocaleString(text.locale, {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      })}`;
  const userHeading = compact && resolvedLanguage === 'en' ? '## Q' : text.userHeading;

  const lines: string[] = [
    headerTitle,
    '',
    headerMeta,
    '',
  ];

  for (const msg of messages) {
    const heading = msg.role === 'user' ? userHeading : text.assistantHeading;
    const localizedSkills = omitSkillLabels
      ? []
      : resolveMessageSkillLabels(msg, resolvedLanguage, options?.skills);
    if (msg.role === 'assistant' && localizedSkills.length > 0) {
      const delimiter = compact ? ',' : resolvedLanguage === 'en' ? ', ' : '、';
      lines.push(`${heading} (${localizedSkills.join(delimiter)})`);
    } else {
      lines.push(heading);
    }
    lines.push('');
    lines.push(msg.content);
    lines.push('');
  }

  return lines.join('\n');
}

/**
 * Format chat session Markdown for the notification endpoint (`max_length=50000`).
 * Uses compact English structural headers when verbose English scaffolding pushes
 * an otherwise valid borderline session over `MAX_CHAT_NOTIFICATION_CHARS`.
 */
export function formatSessionForNotification(
  messages: Message[],
  language?: UiLanguage,
  skills?: ReadonlyArray<LocalizableSkill>,
): string {
  const resolvedLanguage = language ?? getRuntimeInitialLanguage();
  const full = formatSessionAsMarkdown(messages, resolvedLanguage, { skills });
  if (full.length <= MAX_CHAT_NOTIFICATION_CHARS || resolvedLanguage !== 'en') {
    return full;
  }
  const compact = formatSessionAsMarkdown(messages, 'en', { skills, compact: true });
  if (compact.length <= MAX_CHAT_NOTIFICATION_CHARS) {
    return compact;
  }
  return formatSessionAsMarkdown(messages, 'en', {
    skills,
    compact: true,
    omitSkillLabels: true,
  });
}

/**
 * Trigger browser download of session as .md file.
 * Revokes object URL after download to prevent memory leak.
 */
export function downloadSession(
  messages: Message[],
  language?: UiLanguage,
  skills?: ReadonlyArray<LocalizableSkill>,
): void {
  const resolvedLanguage = language ?? getRuntimeInitialLanguage();
  const content = formatSessionAsMarkdown(messages, resolvedLanguage, { skills });
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
  const now = new Date();
  const dateStr = now.toISOString().slice(0, 10).replace(/-/g, '');
  const pad = (n: number) => n.toString().padStart(2, '0');
  const timeStr = pad(now.getHours()) + pad(now.getMinutes());
  const filename = `${CHAT_EXPORT_TEXT[resolvedLanguage].filenamePrefix}_${dateStr}_${timeStr}.md`;

  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
