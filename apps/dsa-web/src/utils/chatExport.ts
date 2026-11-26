import type { UiLanguage } from '../i18n/uiText';
import { localizeSkillLabel } from '../locales/strategyText';
import type { Message } from '../stores/agentChatStore';
import { getRuntimeInitialLanguage } from './uiLanguage';

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

/**
 * Format chat messages as Markdown for export.
 */
export function formatSessionAsMarkdown(messages: Message[], language?: UiLanguage): string {
  const resolvedLanguage = language ?? getRuntimeInitialLanguage();
  const text = CHAT_EXPORT_TEXT[resolvedLanguage];
  const now = new Date();
  const timeStr = now.toLocaleString(text.locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });

  const lines: string[] = [
    text.title,
    '',
    `${text.generatedAt}: ${timeStr}`,
    '',
  ];

  for (const msg of messages) {
    const heading = msg.role === 'user' ? text.userHeading : text.assistantHeading;
    const rawSkills = msg.skillNames?.length
      ? msg.skillNames
      : msg.skillName
        ? [msg.skillName]
        : msg.skills?.length
          ? msg.skills
          : msg.skill
            ? [msg.skill]
            : [];
    const localizedSkills = rawSkills.map((item) => localizeSkillLabel(item, resolvedLanguage));
    if (msg.role === 'assistant' && localizedSkills.length > 0) {
      lines.push(`${heading} (${localizedSkills.join(resolvedLanguage === 'en' ? ', ' : '、')})`);
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
 * Trigger browser download of session as .md file.
 * Revokes object URL after download to prevent memory leak.
 */
export function downloadSession(messages: Message[], language?: UiLanguage): void {
  const resolvedLanguage = language ?? getRuntimeInitialLanguage();
  const content = formatSessionAsMarkdown(messages, resolvedLanguage);
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
