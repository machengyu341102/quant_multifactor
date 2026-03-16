import { Platform } from 'react-native';

const tintColorLight = '#155EEF';
const tintColorDark = '#8CC7FF';

export const Colors = {
  light: {
    text: '#09131F',
    subtext: '#546374',
    background: '#EDF3F9',
    surface: '#FFFFFF',
    surfaceMuted: '#DCE7F3',
    border: '#D5E0EB',
    tint: tintColorLight,
    accentSoft: '#DCE8FF',
    success: '#0E9F6E',
    warning: '#D97706',
    danger: '#C2410C',
    hero: '#07111F',
    icon: '#758397',
    tabIconDefault: '#758397',
    tabIconSelected: tintColorLight,
  },
  dark: {
    text: '#F5F8FC',
    subtext: '#A7B5C6',
    background: '#050A12',
    surface: '#0B1422',
    surfaceMuted: '#102238',
    border: '#16314E',
    tint: tintColorDark,
    accentSoft: '#0D2444',
    success: '#3DD598',
    warning: '#F6B34C',
    danger: '#FF7B72',
    hero: '#08131F',
    icon: '#6E8093',
    tabIconDefault: '#6E8093',
    tabIconSelected: tintColorDark,
  },
};

export const Fonts = Platform.select({
  ios: {
    /** iOS `UIFontDescriptorSystemDesignDefault` */
    sans: 'system-ui',
    /** iOS `UIFontDescriptorSystemDesignSerif` */
    serif: 'ui-serif',
    /** iOS `UIFontDescriptorSystemDesignRounded` */
    rounded: 'ui-rounded',
    /** iOS `UIFontDescriptorSystemDesignMonospaced` */
    mono: 'ui-monospace',
  },
  default: {
    sans: 'normal',
    serif: 'serif',
    rounded: 'normal',
    mono: 'monospace',
  },
  web: {
    sans: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
    serif: "Georgia, 'Times New Roman', serif",
    rounded: "'SF Pro Rounded', 'Hiragino Maru Gothic ProN', Meiryo, 'MS PGothic', sans-serif",
    mono: "SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace",
  },
});

export const Spacing = {
  screen: 20,
  card: 18,
  gap: 14,
};
