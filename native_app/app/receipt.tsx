import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors } from '@/constants/theme';
import {
  actionReceiptTitle,
  parseActionReceiptParams,
} from '@/lib/action-receipt';
import { formatCurrency } from '@/lib/format';
import { useColorScheme } from '@/hooks/use-color-scheme';

export default function ReceiptScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const receipt = parseActionReceiptParams(params);
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];

  return (
    <AppScreen>
      <Pressable
        onPress={() => {
          router.back();
        }}
        style={styles.backButton}>
        <Text style={[styles.backText, { color: palette.tint }]}>返回上一页</Text>
      </Pressable>
      <SurfaceCard style={styles.sectionCard}>
        <Text style={[styles.summaryTitle, { color: palette.text }]}>{actionReceiptTitle(receipt.action)}</Text>
        <Text style={[styles.summaryCopy, { color: palette.subtext }]}>
          {receipt.code || '--'} {receipt.name || ''} · {receipt.message || '本次动作已完成。'}
        </Text>
        <Text style={[styles.summaryHint, { color: palette.text }]}>
          {receipt.hasActivePosition ? '仓位仍在' : '已结束动作'} / 成交 {receipt.quantity} 股
        </Text>
        <Text style={[styles.summaryHint, { color: palette.subtext }]}>
          {receipt.realizedProfitLoss !== null
            ? `已实现盈亏 ${formatCurrency(receipt.realizedProfitLoss)}。`
            : '这次动作还没有产生已实现盈亏。'}
        </Text>
      </SurfaceCard>

      <View style={styles.buttonRow}>
        {receipt.hasActivePosition && receipt.positionCode ? (
          <Pressable
            onPress={() => {
              router.replace({
                pathname: '/position/[code]',
                params: { code: receipt.positionCode ?? receipt.code },
              });
            }}
            style={[styles.primaryButton, { backgroundColor: palette.tint }]}>
            <Text style={styles.primaryButtonText}>查看持仓</Text>
          </Pressable>
        ) : null}
        <Pressable
          onPress={() => {
            router.replace({ pathname: '/records', params: { focus: receipt.code } });
          }}
          style={[
            styles.ghostButton,
            {
              borderColor: palette.border,
            },
          ]}>
          <Text style={[styles.ghostButtonText, { color: palette.text }]}>交易记录</Text>
        </Pressable>
      </View>

      {receipt.source === 'signal' && receipt.signalId ? (
        <Pressable
          onPress={() => {
            router.replace({
              pathname: '/signal/[id]',
              params: { id: receipt.signalId ?? '' },
            });
          }}
          style={styles.linkWrap}>
          <Text style={[styles.linkText, { color: palette.tint }]}>回到原信号页</Text>
        </Pressable>
      ) : null}
    </AppScreen>
  );
}

const styles = StyleSheet.create({
  backButton: {
    alignSelf: 'flex-start',
    paddingVertical: 6,
  },
  backText: {
    fontSize: 14,
    fontWeight: '700',
  },
  sectionCard: {
    gap: 12,
  },
  summaryTitle: {
    fontSize: 16,
    fontWeight: '800',
  },
  summaryCopy: {
    fontSize: 14,
    lineHeight: 21,
  },
  summaryHint: {
    fontSize: 13,
    lineHeight: 20,
  },
  buttonRow: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 4,
  },
  primaryButton: {
    flex: 1,
    minHeight: 48,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 18,
  },
  primaryButtonText: {
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: '800',
  },
  ghostButton: {
    flex: 1,
    minHeight: 48,
    borderRadius: 16,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 18,
  },
  ghostButtonText: {
    fontSize: 15,
    fontWeight: '800',
  },
  linkWrap: {
    alignSelf: 'flex-start',
    paddingVertical: 4,
  },
  linkText: {
    fontSize: 14,
    fontWeight: '700',
  },
});
