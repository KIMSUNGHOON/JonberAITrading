/**
 * LanguageSelector Component
 *
 * Global language toggle for switching between Korean and English.
 * Can be used in header, settings, or anywhere in the app.
 */

import { Globe } from 'lucide-react';
import { useStore, type Language } from '@/store';
import { t } from '@/utils/translations';

interface LanguageSelectorProps {
  /** Display style: 'toggle' for simple switch, 'dropdown' for full dropdown */
  variant?: 'toggle' | 'dropdown';
  /** Show label text next to the selector */
  showLabel?: boolean;
  /** Compact mode for tight spaces */
  compact?: boolean;
}

export function LanguageSelector({
  variant = 'toggle',
  showLabel = false,
  compact = false,
}: LanguageSelectorProps) {
  const language = useStore((state) => state.language);
  const setLanguage = useStore((state) => state.setLanguage);

  const toggleLanguage = () => {
    setLanguage(language === 'ko' ? 'en' : 'ko');
  };

  if (variant === 'dropdown') {
    return (
      <div className="relative inline-flex items-center gap-2">
        {showLabel && (
          <span className="text-sm text-gray-400">
            {t('settings_language', language)}
          </span>
        )}
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value as Language)}
          className={`
            bg-gray-800 border border-gray-700 rounded-lg text-white
            focus:ring-2 focus:ring-blue-500 focus:border-blue-500
            ${compact ? 'px-2 py-1 text-xs' : 'px-3 py-2 text-sm'}
          `}
        >
          <option value="ko">{t('settings_language_ko', language)}</option>
          <option value="en">{t('settings_language_en', language)}</option>
        </select>
      </div>
    );
  }

  // Toggle variant (default)
  return (
    <button
      onClick={toggleLanguage}
      className={`
        inline-flex items-center gap-2 rounded-lg border border-gray-700
        bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-white
        transition-colors
        ${compact ? 'px-2 py-1' : 'px-3 py-2'}
      `}
      title={t('settings_language', language)}
    >
      <Globe className={compact ? 'w-3.5 h-3.5' : 'w-4 h-4'} />
      <span className={`font-medium ${compact ? 'text-xs' : 'text-sm'}`}>
        {language === 'ko' ? '한국어' : 'EN'}
      </span>
    </button>
  );
}

/**
 * Minimal language toggle button (icon only)
 */
export function LanguageToggleButton() {
  const language = useStore((state) => state.language);
  const setLanguage = useStore((state) => state.setLanguage);

  const toggleLanguage = () => {
    setLanguage(language === 'ko' ? 'en' : 'ko');
  };

  return (
    <button
      onClick={toggleLanguage}
      className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition-colors"
      title={`${t('settings_language', language)}: ${language === 'ko' ? 'English' : '한국어'}`}
    >
      <div className="relative">
        <Globe className="w-5 h-5" />
        <span className="absolute -bottom-1 -right-1 text-[8px] font-bold bg-gray-700 px-1 rounded">
          {language.toUpperCase()}
        </span>
      </div>
    </button>
  );
}
