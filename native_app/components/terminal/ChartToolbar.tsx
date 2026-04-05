import { Ionicons } from '@expo/vector-icons';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { terminalTheme } from '@/constants/terminal-theme';
import type {
  ChartInterval,
  ChartType,
  DrawToolKey,
  IndicatorKey,
  UtilityToolKey,
} from '@/mocks/terminal-data';

const INTERVALS: ChartInterval[] = ['1m', '5m', '15m', '1h', '4h', '1D', '1W'];
const TYPES: { key: ChartType; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { key: 'candles', label: 'K线', icon: 'stats-chart-outline' },
  { key: 'area', label: '面积', icon: 'analytics-outline' },
  { key: 'line', label: '线图', icon: 'pulse-outline' },
];
const INDICATORS: IndicatorKey[] = ['MA', 'EMA', 'MACD', 'RSI', 'VOL'];
const DRAW_TOOLS: { key: DrawToolKey; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { key: 'trendline', label: '趋势线', icon: 'trending-up-outline' },
  { key: 'horizontal', label: '水平线', icon: 'remove-outline' },
  { key: 'fibonacci', label: '斐波那契', icon: 'git-branch-outline' },
  { key: 'note', label: '标注', icon: 'create-outline' },
];
const UTILITY_TOOLS: { key: UtilityToolKey; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { key: 'crosshair', label: '十字线', icon: 'add-outline' },
  { key: 'compare', label: '比较', icon: 'git-compare-outline' },
  { key: 'reset', label: '重置', icon: 'refresh-outline' },
  { key: 'fullscreen', label: '全屏', icon: 'expand-outline' },
  { key: 'capture', label: '截图', icon: 'camera-outline' },
];

interface ChartToolbarProps {
  interval: ChartInterval;
  chartType: ChartType;
  indicators: IndicatorKey[];
  drawTool: DrawToolKey;
  utilityTools: UtilityToolKey[];
  transientTools: UtilityToolKey[];
  onChangeInterval: (interval: ChartInterval) => void;
  onChangeChartType: (type: ChartType) => void;
  onToggleIndicator: (indicator: IndicatorKey) => void;
  onSelectDrawTool: (tool: DrawToolKey) => void;
  onToggleUtilityTool: (tool: UtilityToolKey) => void;
}

export function ChartToolbar({
  interval,
  chartType,
  indicators,
  drawTool,
  utilityTools,
  transientTools,
  onChangeInterval,
  onChangeChartType,
  onToggleIndicator,
  onSelectDrawTool,
  onToggleUtilityTool,
}: ChartToolbarProps) {
  return (
    <View style={styles.container}>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.scrollContent}>
        <View style={styles.group}>
          {INTERVALS.map((item) => {
            const active = item === interval;
            return (
              <Pressable
                key={item}
                onPress={() => onChangeInterval(item)}
                style={({ hovered, pressed }) => [
                  styles.textButton,
                  active && styles.buttonActive,
                  hovered && !active && styles.buttonHover,
                  pressed && styles.buttonPressed,
                ]}>
                <Text style={[styles.textButtonText, active && styles.buttonTextActive]}>{item}</Text>
              </Pressable>
            );
          })}
        </View>

        <Divider />

        <View style={styles.group}>
          {TYPES.map((item) => {
            const active = item.key === chartType;
            return (
              <ToolButton
                key={item.key}
                active={active}
                label={item.label}
                icon={item.icon}
                onPress={() => onChangeChartType(item.key)}
              />
            );
          })}
        </View>

        <Divider />

        <View style={styles.group}>
          {INDICATORS.map((item) => (
            <Pressable
              key={item}
              onPress={() => onToggleIndicator(item)}
              style={({ hovered, pressed }) => [
                styles.textButton,
                indicators.includes(item) && styles.buttonActive,
                hovered && !indicators.includes(item) && styles.buttonHover,
                pressed && styles.buttonPressed,
              ]}>
              <Text style={[styles.textButtonText, indicators.includes(item) && styles.buttonTextActive]}>
                {item}
              </Text>
            </Pressable>
          ))}
        </View>

        <Divider />

        <View style={styles.group}>
          {DRAW_TOOLS.map((item) => (
            <ToolButton
              key={item.key}
              active={drawTool === item.key}
              label={item.label}
              icon={item.icon}
              onPress={() => onSelectDrawTool(item.key)}
            />
          ))}
        </View>

        <Divider />

        <View style={styles.group}>
          {UTILITY_TOOLS.map((item) => {
            const active = utilityTools.includes(item.key) || transientTools.includes(item.key);
            return (
              <ToolButton
                key={item.key}
                active={active}
                label={item.label}
                icon={item.icon}
                onPress={() => onToggleUtilityTool(item.key)}
              />
            );
          })}
        </View>
      </ScrollView>
    </View>
  );
}

function ToolButton({
  active,
  label,
  icon,
  onPress,
}: {
  active: boolean;
  label: string;
  icon: keyof typeof Ionicons.glyphMap;
  onPress: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      style={({ hovered, pressed }) => [
        styles.toolButton,
        active && styles.buttonActive,
        hovered && !active && styles.buttonHover,
        pressed && styles.buttonPressed,
      ]}>
      <Ionicons
        name={icon}
        size={14}
        color={active ? terminalTheme.colors.text : terminalTheme.colors.subtext}
      />
      <Text style={[styles.toolButtonText, active && styles.buttonTextActive]}>{label}</Text>
    </Pressable>
  );
}

function Divider() {
  return <View style={styles.divider} />;
}

const styles = StyleSheet.create({
  container: {
    minHeight: 52,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    borderRadius: terminalTheme.radius.md,
    backgroundColor: terminalTheme.colors.panel,
    paddingHorizontal: terminalTheme.spacing.md,
    justifyContent: 'center',
  },
  scrollContent: {
    alignItems: 'center',
    gap: terminalTheme.spacing.sm,
  },
  group: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: terminalTheme.spacing.xs,
  },
  divider: {
    width: 1,
    alignSelf: 'stretch',
    backgroundColor: terminalTheme.colors.border,
    marginHorizontal: terminalTheme.spacing.xs,
  },
  textButton: {
    minHeight: 30,
    paddingHorizontal: 10,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    borderRadius: terminalTheme.radius.sm,
    backgroundColor: terminalTheme.colors.panelMuted,
    alignItems: 'center',
    justifyContent: 'center',
  },
  textButtonText: {
    color: terminalTheme.colors.subtext,
    fontSize: 12,
    fontWeight: '600',
    fontFamily: terminalTheme.fonts.mono,
  },
  toolButton: {
    minHeight: 30,
    paddingHorizontal: 10,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    borderRadius: terminalTheme.radius.sm,
    backgroundColor: terminalTheme.colors.panelMuted,
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
    gap: 6,
  },
  toolButtonText: {
    color: terminalTheme.colors.subtext,
    fontSize: 11,
    fontWeight: '600',
    fontFamily: terminalTheme.fonts.sans,
  },
  buttonActive: {
    borderColor: terminalTheme.colors.accent,
    backgroundColor: terminalTheme.colors.accentSoft,
  },
  buttonHover: {
    backgroundColor: terminalTheme.colors.hover,
  },
  buttonPressed: {
    backgroundColor: terminalTheme.colors.active,
  },
  buttonTextActive: {
    color: terminalTheme.colors.text,
  },
  focusRing: {
    borderColor: terminalTheme.colors.focus,
  },
});
