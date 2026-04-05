import { useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { terminalTheme } from '@/constants/terminal-theme';

type TradeSide = 'buy' | 'sell';
type TradeOrderType = 'limit' | 'market' | 'stop';

const ORDER_TYPE_LABELS: Record<TradeOrderType, string> = {
  limit: '限价',
  market: '市价',
  stop: '止损',
};

const SIDE_LABELS: Record<TradeSide, string> = {
  buy: '买入',
  sell: '卖出',
};

interface QuickTradeCardProps {
  latestPrice: number;
  orderSide: TradeSide;
  orderType: TradeOrderType;
  priceValue: string;
  quantityValue: string;
  activeAllocation: number | null;
  availableBalance: string;
  onChangeOrderSide: (side: TradeSide) => void;
  onChangeOrderType: (type: TradeOrderType) => void;
  onChangePriceValue: (value: string) => void;
  onChangeQuantityValue: (value: string) => void;
  onChangeAllocation: (value: number) => void;
}

export function QuickTradeCard({
  latestPrice,
  orderSide,
  orderType,
  priceValue,
  quantityValue,
  activeAllocation,
  availableBalance,
  onChangeOrderSide,
  onChangeOrderType,
  onChangePriceValue,
  onChangeQuantityValue,
  onChangeAllocation,
}: QuickTradeCardProps) {
  const [focusField, setFocusField] = useState<'price' | 'qty' | null>(null);
  const entryPrice = orderType === 'market' ? latestPrice : Number(priceValue || latestPrice);
  const quantity = Number(quantityValue || 0);
  const estimate = Number.isFinite(entryPrice * quantity) ? entryPrice * quantity : 0;
  const primaryColor = orderSide === 'buy' ? terminalTheme.colors.buy : terminalTheme.colors.sell;

  return (
    <View style={styles.card}>
      <Text style={styles.title}>快速下单</Text>

      <View style={styles.segment}>
        {(['buy', 'sell'] as TradeSide[]).map((item) => {
          const active = item === orderSide;
          return (
            <Pressable
              key={item}
              onPress={() => onChangeOrderSide(item)}
              style={({ hovered, pressed }) => [
                styles.segmentButton,
                active && { backgroundColor: item === 'buy' ? terminalTheme.colors.buySoft : terminalTheme.colors.sellSoft, borderColor: primaryColor },
                hovered && !active && styles.segmentButtonHover,
                pressed && styles.segmentButtonPressed,
              ]}>
              <Text
                style={[
                  styles.segmentText,
                  active && { color: item === 'buy' ? terminalTheme.colors.buy : terminalTheme.colors.sell },
                ]}>
                {SIDE_LABELS[item]}
              </Text>
            </Pressable>
          );
        })}
      </View>

      <View style={styles.segment}>
        {(['limit', 'market', 'stop'] as TradeOrderType[]).map((item) => {
          const active = item === orderType;
          return (
            <Pressable
              key={item}
              onPress={() => onChangeOrderType(item)}
              style={({ hovered, pressed }) => [
                styles.modeButton,
                active && styles.modeButtonActive,
                hovered && !active && styles.segmentButtonHover,
                pressed && styles.segmentButtonPressed,
              ]}>
              <Text style={[styles.modeText, active && styles.modeTextActive]}>{ORDER_TYPE_LABELS[item]}</Text>
            </Pressable>
          );
        })}
      </View>

      <Field
        label={orderType === 'stop' ? '触发价' : '价格'}
        value={orderType === 'market' ? latestPrice.toFixed(2) : priceValue}
        editable={orderType !== 'market'}
        focused={focusField === 'price'}
        onFocus={() => setFocusField('price')}
        onBlur={() => setFocusField(null)}
        onChangeText={onChangePriceValue}
      />

      <Field
        label="数量"
        value={quantityValue}
        editable
        focused={focusField === 'qty'}
        onFocus={() => setFocusField('qty')}
        onBlur={() => setFocusField(null)}
        onChangeText={onChangeQuantityValue}
      />

      <View style={styles.allocationRow}>
        {[25, 50, 75, 100].map((value) => {
          const active = activeAllocation === value;
          return (
            <Pressable
              key={value}
              onPress={() => onChangeAllocation(value)}
              style={({ hovered, pressed }) => [
                styles.allocationButton,
                active && styles.modeButtonActive,
                hovered && !active && styles.segmentButtonHover,
                pressed && styles.segmentButtonPressed,
              ]}>
              <Text style={[styles.allocationText, active && styles.modeTextActive]}>{value}%</Text>
            </Pressable>
          );
        })}
      </View>

      <View style={styles.metaRow}>
        <Text style={styles.metaLabel}>预计成交额</Text>
        <Text style={styles.metaValue}>{estimate.toLocaleString('en-US', { maximumFractionDigits: 2 })}</Text>
      </View>
      <View style={styles.metaRow}>
        <Text style={styles.metaLabel}>可用余额</Text>
        <Text style={styles.metaValue}>{availableBalance}</Text>
      </View>

      <Pressable style={[styles.submitButton, { backgroundColor: primaryColor }]}>
        <Text style={styles.submitText}>
          {orderSide === 'buy' ? '提交买入' : '提交卖出'}
        </Text>
      </Pressable>
      <Text style={styles.riskHint}>仅演示界面。实际下单前请确认账户环境、价格精度与风险约束。</Text>
    </View>
  );
}

function Field({
  label,
  value,
  editable,
  focused,
  onFocus,
  onBlur,
  onChangeText,
}: {
  label: string;
  value: string;
  editable: boolean;
  focused: boolean;
  onFocus: () => void;
  onBlur: () => void;
  onChangeText: (value: string) => void;
}) {
  return (
    <View style={styles.fieldGroup}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        value={value}
        editable={editable}
        onFocus={onFocus}
        onBlur={onBlur}
        onChangeText={onChangeText}
        keyboardType="decimal-pad"
        placeholder="输入"
        placeholderTextColor={terminalTheme.colors.muted}
        style={[
          styles.fieldInput,
          focused && styles.focusRing,
          !editable && styles.fieldInputDisabled,
        ]}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    borderRadius: terminalTheme.radius.md,
    backgroundColor: terminalTheme.colors.panel,
    padding: terminalTheme.spacing.md,
    gap: terminalTheme.spacing.sm,
  },
  title: {
    color: terminalTheme.colors.text,
    fontSize: 13,
    fontWeight: '700',
  },
  segment: {
    flexDirection: 'row',
    gap: 8,
  },
  segmentButton: {
    flex: 1,
    minHeight: 34,
    borderRadius: terminalTheme.radius.sm,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.panelMuted,
    alignItems: 'center',
    justifyContent: 'center',
  },
  segmentButtonHover: {
    backgroundColor: terminalTheme.colors.hover,
  },
  segmentButtonPressed: {
    backgroundColor: terminalTheme.colors.active,
  },
  segmentText: {
    color: terminalTheme.colors.subtext,
    fontSize: 12,
    fontWeight: '700',
  },
  modeButton: {
    flex: 1,
    minHeight: 32,
    borderRadius: terminalTheme.radius.sm,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.chartBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  modeButtonActive: {
    borderColor: terminalTheme.colors.accent,
    backgroundColor: terminalTheme.colors.accentSoft,
  },
  modeText: {
    color: terminalTheme.colors.subtext,
    fontSize: 11,
    fontWeight: '600',
  },
  modeTextActive: {
    color: terminalTheme.colors.text,
  },
  fieldGroup: {
    gap: 6,
  },
  fieldLabel: {
    color: terminalTheme.colors.subtext,
    fontSize: 11,
  },
  fieldInput: {
    minHeight: 40,
    borderRadius: terminalTheme.radius.sm,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.chartBg,
    color: terminalTheme.colors.text,
    paddingHorizontal: 12,
    fontSize: 13,
    fontFamily: terminalTheme.fonts.mono,
  },
  fieldInputDisabled: {
    opacity: 0.7,
  },
  allocationRow: {
    flexDirection: 'row',
    gap: 8,
  },
  allocationButton: {
    flex: 1,
    minHeight: 30,
    borderRadius: terminalTheme.radius.sm,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.panelMuted,
    alignItems: 'center',
    justifyContent: 'center',
  },
  allocationText: {
    color: terminalTheme.colors.subtext,
    fontSize: 11,
    fontWeight: '700',
    fontFamily: terminalTheme.fonts.mono,
  },
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  metaLabel: {
    color: terminalTheme.colors.subtext,
    fontSize: 11,
  },
  metaValue: {
    color: terminalTheme.colors.text,
    fontSize: 12,
    fontFamily: terminalTheme.fonts.mono,
  },
  submitButton: {
    minHeight: 42,
    borderRadius: terminalTheme.radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
  },
  submitText: {
    color: terminalTheme.colors.white,
    fontSize: 13,
    fontWeight: '800',
  },
  riskHint: {
    color: terminalTheme.colors.subtext,
    fontSize: 10,
    lineHeight: 15,
  },
  focusRing: {
    borderColor: terminalTheme.colors.focus,
  },
});
