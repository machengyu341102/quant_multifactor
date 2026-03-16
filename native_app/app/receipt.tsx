import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { MetricCard } from '@/components/app/metric-card';
import { SectionHeading } from '@/components/app/section-heading';
import { StatusPill } from '@/components/app/status-pill';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors, Spacing } from '@/constants/theme';
import {
  actionReceiptTitle,
  actionReceiptTone,
  parseActionReceiptParams,
} from '@/lib/action-receipt';
import { formatCurrency, formatTimestamp } from '@/lib/format';
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
      <Pressable
        onPress={() => {
          router.push({
            pathname: '/feedback',
            params: {
              title: receipt.code ? `${receipt.code} 动作回执反馈` : '动作回执反馈',
              message: receipt.code
                ? `我在查看 ${receipt.code} 的动作回执时，建议优化：`
                : '我在查看动作回执时，建议优化：',
              category: 'ux',
              sourceType: 'receipt',
              sourceId: receipt.code || '',
              sourceRoute: '/receipt',
            },
          });
        }}
        style={styles.feedbackButton}>
        <Text style={[styles.feedbackButtonText, { color: palette.tint }]}>提意见</Text>
      </Pressable>

      <View style={[styles.hero, { backgroundColor: palette.hero }]}>
        <Text style={styles.heroEyebrow}>ACTION RECEIPT</Text>
        <Text style={styles.heroTitle}>{actionReceiptTitle(receipt.action)}</Text>
        <Text style={styles.heroCopy}>
          {receipt.code || '--'} {receipt.name || ''} · {receipt.message || '本次动作已完成。'}
        </Text>
        <View style={styles.heroPills}>
          <StatusPill label={actionReceiptTitle(receipt.action)} tone={actionReceiptTone(receipt.action)} />
          <StatusPill
            label={receipt.hasActivePosition ? '仓位仍在' : '已结束动作'}
            tone={receipt.hasActivePosition ? 'info' : 'neutral'}
          />
        </View>
      </View>

      <SectionHeading
        title="一页结果摘要"
        subtitle="先把动作结果、资金变化和下一步压成一页，再往下看完整回执。"
      />
      <SurfaceCard style={styles.sectionCard}>
        <View style={styles.snapshotGrid}>
          <View style={[styles.snapshotCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <Text style={[styles.snapshotStep, { color: palette.tint }]}>01 动作结果</Text>
            <Text style={[styles.snapshotTitle, { color: palette.text }]}>{actionReceiptTitle(receipt.action)}</Text>
            <Text style={[styles.snapshotCopy, { color: palette.subtext }]}>
              {receipt.code || '--'} {receipt.name || ''}
            </Text>
            <Text style={[styles.snapshotBody, { color: palette.text }]}>
              {receipt.message || '本次动作已完成。'}
            </Text>
          </View>

          <View style={[styles.snapshotCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <Text style={[styles.snapshotStep, { color: palette.tint }]}>02 资金变化</Text>
            <Text style={[styles.snapshotTitle, { color: palette.text }]}>
              成交 {receipt.quantity} 股 / {receipt.executionPrice.toFixed(2)}
            </Text>
            <Text style={[styles.snapshotCopy, { color: palette.subtext }]}>
              现金 {formatCurrency(receipt.cashBalance)} / 总资产 {formatCurrency(receipt.totalAssets)}
            </Text>
            <Text style={[styles.snapshotBody, { color: palette.text }]}>
              {receipt.realizedProfitLoss !== null
                ? `已实现盈亏 ${formatCurrency(receipt.realizedProfitLoss)}。`
                : '这次动作还没有产生已实现盈亏。'}
            </Text>
          </View>

          <View style={[styles.snapshotCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <Text style={[styles.snapshotStep, { color: palette.tint }]}>03 下一步</Text>
            <Text style={[styles.snapshotTitle, { color: palette.text }]}>
              {receipt.hasActivePosition ? '回到持仓继续管理' : '回到记录复盘'}
            </Text>
            <Text style={[styles.snapshotCopy, { color: palette.subtext }]}>
              {receipt.executedAt ? formatTimestamp(receipt.executedAt.replace(' ', 'T')) : '--'}
            </Text>
            <Text style={[styles.snapshotBody, { color: palette.text }]}>
              {receipt.hasActivePosition
                ? '服务端已经记账完成，下一步直接去持仓页看保护线和后续动作。'
                : '动作已经结束，下一步更适合去交易记录和复盘链路看结果。'}
            </Text>
          </View>
        </View>
      </SurfaceCard>

      <SectionHeading title="执行摘要" subtitle="这里显示的是服务端确认结果，不是前端自己猜的动作状态。" />
      <View style={styles.grid}>
        <MetricCard label="成交数量" value={`${receipt.quantity}`} tone="neutral" />
        <MetricCard label="成交价格" value={receipt.executionPrice.toFixed(2)} tone="info" />
        <MetricCard label="可用资金" value={formatCurrency(receipt.cashBalance)} tone="neutral" />
        <MetricCard label="总资产" value={formatCurrency(receipt.totalAssets)} tone="info" />
        {receipt.realizedProfitLoss !== null ? (
          <MetricCard
            label="已实现盈亏"
            value={formatCurrency(receipt.realizedProfitLoss)}
            tone={receipt.realizedProfitLoss >= 0 ? 'success' : 'danger'}
          />
        ) : null}
      </View>

      <SurfaceCard style={styles.sectionCard}>
        <Text style={[styles.summaryTitle, { color: palette.text }]}>这张回执怎么理解</Text>
        <Text style={[styles.summaryCopy, { color: palette.subtext }]}>
          回执的意义不是告诉你“按钮点成功了”，而是确认服务端已经记账、仓位和资金都按这次动作更新完成。
        </Text>
        <View style={styles.rowBetween}>
          <Text style={[styles.rowLabel, { color: palette.subtext }]}>服务端确认时间</Text>
          <Text style={[styles.rowValue, { color: palette.text }]}>
            {receipt.executedAt ? formatTimestamp(receipt.executedAt.replace(' ', 'T')) : '--'}
          </Text>
        </View>
        <View style={styles.rowBetween}>
          <Text style={[styles.rowLabel, { color: palette.subtext }]}>动作对象</Text>
          <Text style={[styles.rowValue, { color: palette.text }]}>
            {receipt.code || '--'} {receipt.name || ''}
          </Text>
        </View>
        <View style={styles.rowBetween}>
          <Text style={[styles.rowLabel, { color: palette.subtext }]}>动作结果</Text>
          <Text style={[styles.rowValue, { color: palette.text }]}>{receipt.message || '--'}</Text>
        </View>
      </SurfaceCard>

      <SectionHeading title="下一步" subtitle="做完动作以后，直接去看仓位或交易记录，不再丢链路。" />
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
  feedbackButton: {
    alignSelf: 'flex-start',
    paddingVertical: 4,
  },
  backText: {
    fontSize: 14,
    fontWeight: '700',
  },
  feedbackButtonText: {
    fontSize: 13,
    fontWeight: '700',
  },
  hero: {
    borderRadius: 28,
    padding: 24,
    gap: 12,
  },
  heroEyebrow: {
    color: '#8CC7FF',
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1.4,
  },
  heroTitle: {
    color: '#F7FBFF',
    fontSize: 28,
    fontWeight: '800',
    lineHeight: 34,
  },
  heroCopy: {
    color: '#C8D8EB',
    fontSize: 15,
    lineHeight: 22,
  },
  heroPills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: Spacing.gap,
  },
  sectionCard: {
    gap: 12,
  },
  snapshotGrid: {
    gap: 12,
  },
  snapshotCard: {
    borderWidth: 1,
    borderRadius: 20,
    padding: 14,
    gap: 8,
  },
  snapshotStep: {
    fontSize: 12,
    fontWeight: '800',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  snapshotTitle: {
    fontSize: 17,
    fontWeight: '800',
    lineHeight: 23,
  },
  snapshotCopy: {
    fontSize: 13,
    lineHeight: 20,
  },
  snapshotBody: {
    fontSize: 14,
    lineHeight: 22,
  },
  summaryTitle: {
    fontSize: 16,
    fontWeight: '800',
  },
  summaryCopy: {
    fontSize: 14,
    lineHeight: 21,
  },
  rowBetween: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
  },
  rowLabel: {
    fontSize: 14,
  },
  rowValue: {
    flex: 1,
    fontSize: 14,
    fontWeight: '700',
    textAlign: 'right',
  },
  buttonRow: {
    flexDirection: 'row',
    gap: 10,
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
