import { Platform } from 'react-native';

const tintColorLight = '#14804A';
const tintColorDark = '#7EE2A8';

export const Colors = {
  light: {
    text: '#102017',
    subtext: '#5A6D61',
    background: '#EEF6F0',
    surface: '#FFFFFF',
    surfaceMuted: '#E2EEE6',
    border: '#D6E4DA',
    tint: tintColorLight,
    accentSoft: '#DFF4E7',
    success: '#157347',
    warning: '#B7791F',
    danger: '#C2410C',
    hero: '#123222',
    icon: '#708377',
    tabIconDefault: '#708377',
    tabIconSelected: tintColorLight,
  },
  dark: {
    text: '#F3FBF5',
    subtext: '#A7C2B0',
    background: '#07110B',
    surface: '#0E1912',
    surfaceMuted: '#14261B',
    border: '#1E3828',
    tint: tintColorDark,
    accentSoft: '#173624',
    success: '#45D28A',
    warning: '#F0BD63',
    danger: '#FF7B72',
    hero: '#0B2015',
    icon: '#7C9386',
    tabIconDefault: '#7C9386',
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
  screen: 12,
  card: 12,
  gap: 8,
};
