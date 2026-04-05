import { Ionicons } from '@expo/vector-icons';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { terminalTheme } from '@/constants/terminal-theme';
import type { TerminalMarketCategory } from '@/mocks/terminal-data';
import { getHoverState } from './pressable-state';

const MARKET_OPTIONS: { key: TerminalMarketCategory; label: string }[] = [
  { key: 'stocks', label: '股票' },
  { key: 'crypto', label: '加密' },
  { key: 'forex', label: '外汇' },
  { key: 'futures', label: '期货' },
];

interface TerminalHeaderProps {
  marketCategory: TerminalMarketCategory;
  searchValue: string;
  currentTimeLabel: string;
  marketStatusLabel: string;
  onChangeMarketCategory: (category: TerminalMarketCategory) => void;
  onChangeSearchValue: (value: string) => void;
}

export function TerminalHeader({
  marketCategory,
  searchValue,
  currentTimeLabel,
  marketStatusLabel,
  onChangeMarketCategory,
  onChangeSearchValue,
}: TerminalHeaderProps) {
  return (
    <View style={styles.container}>
      <View style={styles.leftGroup}>
        <View style={styles.logoBox}>
          <Text style={styles.logoText}>A</Text>
        </View>
        <View style={styles.productBlock}>
          <Text style={styles.productName}>Alpha Terminal</Text>
          <View style={styles.marketSwitch}>
            {MARKET_OPTIONS.map((option) => {
              const active = option.key === marketCategory;
              return (
                <Pressable
                  key={option.key}
                  accessibilityRole="tab"
                  accessibilityState={{ selected: active }}
                  onPress={() => onChangeMarketCategory(option.key)}
                  style={(state) => {
                    const hovered = getHoverState(state);
                    const { pressed } = state;
                    return [
                      styles.marketButton,
                      active && styles.marketButtonActive,
                      hovered && !active && styles.marketButtonHover,
                      pressed && styles.marketButtonPressed,
                    ];
                  }}>
                  <Text style={[styles.marketButtonText, active && styles.marketButtonTextActive]}>
                    {option.label}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </View>
      </View>

      <View style={styles.searchShell}>
        <Ionicons name="search-outline" size={16} color={terminalTheme.colors.subtext} />
        <TextInput
          accessibilityLabel="搜索代码或名称"
          autoCorrect={false}
          autoCapitalize="characters"
          value={searchValue}
          onChangeText={onChangeSearchValue}
          placeholder="搜索代码 / 名称"
          placeholderTextColor={terminalTheme.colors.muted}
          style={styles.searchInput}
        />
      </View>

      <View style={styles.rightGroup}>
        <View style={styles.metaBadge}>
          <Ionicons name="radio-outline" size={13} color={terminalTheme.colors.buy} />
          <Text style={styles.metaBadgeText}>{marketStatusLabel}</Text>
        </View>
        <Text style={styles.timeText}>{currentTimeLabel}</Text>
        <Pressable
          accessibilityRole="button"
          style={(state) => {
            const hovered = getHoverState(state);
            const { pressed } = state;
            return [
              styles.actionButton,
              hovered && styles.actionButtonHover,
              pressed && styles.actionButtonPressed,
            ];
          }}>
          <Ionicons name="wallet-outline" size={15} color={terminalTheme.colors.text} />
          <Text style={styles.actionButtonText}>账户</Text>
        </Pressable>
        <Pressable
          accessibilityRole="button"
          style={(state) => {
            const hovered = getHoverState(state);
            const { pressed } = state;
            return [
              styles.iconButton,
              hovered && styles.actionButtonHover,
              pressed && styles.actionButtonPressed,
            ];
          }}>
          <Ionicons name="person-circle-outline" size={20} color={terminalTheme.colors.text} />
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    minHeight: terminalTheme.layout.headerHeight,
    borderBottomWidth: 1,
    borderBottomColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.page,
    paddingHorizontal: terminalTheme.spacing.lg,
    flexDirection: 'row',
    alignItems: 'center',
    gap: terminalTheme.spacing.md,
  },
  leftGroup: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: terminalTheme.spacing.md,
    minWidth: 320,
  },
  logoBox: {
    width: 28,
    height: 28,
    borderRadius: terminalTheme.radius.sm,
    backgroundColor: terminalTheme.colors.active,
    borderWidth: 1,
    borderColor: terminalTheme.colors.borderStrong,
    alignItems: 'center',
    justifyContent: 'center',
  },
  logoText: {
    color: terminalTheme.colors.text,
    fontSize: 14,
    fontWeight: '800',
    fontFamily: terminalTheme.fonts.mono,
  },
  productBlock: {
    gap: terminalTheme.spacing.xs,
  },
  productName: {
    color: terminalTheme.colors.text,
    fontSize: 14,
    lineHeight: 18,
    fontWeight: '700',
    fontFamily: terminalTheme.fonts.sans,
  },
  marketSwitch: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: terminalTheme.spacing.xs,
  },
  marketButton: {
    minHeight: 24,
    paddingHorizontal: 10,
    borderRadius: terminalTheme.radius.sm,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.panel,
    alignItems: 'center',
    justifyContent: 'center',
  },
  marketButtonActive: {
    borderColor: terminalTheme.colors.accent,
    backgroundColor: terminalTheme.colors.accentSoft,
  },
  marketButtonHover: {
    backgroundColor: terminalTheme.colors.hover,
  },
  marketButtonPressed: {
    backgroundColor: terminalTheme.colors.active,
  },
  marketButtonText: {
    color: terminalTheme.colors.subtext,
    fontSize: 11,
    fontWeight: '600',
    fontFamily: terminalTheme.fonts.sans,
  },
  marketButtonTextActive: {
    color: terminalTheme.colors.text,
  },
  searchShell: {
    flex: 1,
    minHeight: 38,
    paddingHorizontal: 12,
    borderRadius: terminalTheme.radius.sm,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.panel,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  searchInput: {
    flex: 1,
    color: terminalTheme.colors.text,
    fontSize: 13,
    paddingVertical: 0,
    fontFamily: terminalTheme.fonts.sans,
  },
  rightGroup: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'flex-end',
    gap: terminalTheme.spacing.sm,
    minWidth: 270,
  },
  metaBadge: {
    minHeight: 28,
    paddingHorizontal: 10,
    borderRadius: terminalTheme.radius.sm,
    backgroundColor: terminalTheme.colors.panel,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  metaBadgeText: {
    color: terminalTheme.colors.text,
    fontSize: 12,
    fontWeight: '600',
    fontFamily: terminalTheme.fonts.sans,
  },
  timeText: {
    color: terminalTheme.colors.subtext,
    fontSize: 12,
    fontFamily: terminalTheme.fonts.mono,
  },
  actionButton: {
    minHeight: 30,
    paddingHorizontal: 12,
    borderRadius: terminalTheme.radius.sm,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.panel,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  actionButtonText: {
    color: terminalTheme.colors.text,
    fontSize: 12,
    fontWeight: '600',
    fontFamily: terminalTheme.fonts.sans,
  },
  iconButton: {
    width: 32,
    height: 32,
    borderRadius: terminalTheme.radius.sm,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.panel,
    alignItems: 'center',
    justifyContent: 'center',
  },
  actionButtonHover: {
    backgroundColor: terminalTheme.colors.hover,
  },
  actionButtonPressed: {
    backgroundColor: terminalTheme.colors.active,
  },
  focusRing: {
    borderColor: terminalTheme.colors.focus,
  },
});
