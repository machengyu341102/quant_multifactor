import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors } from '@/constants/theme';
import { formatPercent, formatTimestamp } from '@/lib/format';
import {
  getCompositePicks,
  getSignals,
} from '@/lib/api';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRemoteResource } from '@/hooks/use-remote-resource';
import { useAuth } from '@/providers/auth-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';
import type {
  CompositePick,
  Signal,
} from '@/types/trading';

type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

function buildRecommendation(signal: Signal): {
  verdict: string;
  tone: Tone;
  summary: string;
  reasons: string[];
  riskText: string;
  actionHint: string;
} {
  const reasons = [
    `${signal.strategy} 当前在发出这条推荐。`,
    `综合评分 ${signal.score.toFixed(3)}，风险收益比 ${signal.riskReward.toFixed(1)}。`,
  ];

  if (signal.consensusCount > 1) {
    reasons.push(`${signal.consensusCount} 个策略同时给出共识。`);
  } else if (signal.changePct > 0 && signal.changePct < 4) {
    reasons.push('涨幅还没有失控，位置不算特别拥挤。');
  } else if (signal.changePct <= 0) {
    reasons.push('当天没有明显冲高，适合继续观察入场节奏。');
  }

  if (signal.score >= 0.92 && signal.riskReward >= 2) {
    return {
      verdict: '可以执行',
      tone: 'success',
      summary: '评分和盈亏结构同时在线，适合优先做完整判断。',
      reasons: reasons.slice(0, 3),
      riskText: `止损 ${signal.stopLoss.toFixed(2)}，目标 ${signal.targetPrice.toFixed(2)}，失效就不要硬扛。`,
      actionHint: '先看详情，确认位置和环境后再下第一笔。',
    };
  }

  if (signal.changePct >= 5) {
    return {
      verdict: '不建议追高',
      tone: 'warning',
      summary: '票不一定差，但当前位置太热，先防止情绪化追价。',
      reasons: reasons.slice(0, 2),
      riskText: `当前涨幅 ${formatPercent(signal.changePct / 100)}，更适合等回落或去诊股确认。`,
      actionHint: '先放进观察队列，等位置舒服再说。',
    };
  }

  if (signal.score >= 0.84) {
    return {
      verdict: '优先观察',
      tone: 'info',
      summary: '信号质量够看，但还差最后一脚确认。',
      reasons: reasons.slice(0, 3),
      riskText: `先盯 ${signal.stopLoss.toFixed(2)} 这条线，没把握就别急着执行。`,
      actionHint: '适合去决策台复诊，确认环境和个股状态。',
    };
  }

  return {
    verdict: '继续观察',
    tone: 'warning',
    summary: '这条推荐更像备选，不值得抢在最前面出手。',
    reasons: reasons.slice(0, 2),
    riskText: `评分还不够硬，先观察而不是直接上手。止损线 ${signal.stopLoss.toFixed(2)}。`,
    actionHint: '保留在推荐池里，等更强信号或更好位置。',
  };
}

function buildCompositeRecommendation(pick: CompositePick): {
  verdict: string;
  tone: Tone;
  summary: string;
} {
  if (pick.eventBias === '偏空' && pick.eventScore < 45) {
    return {
      verdict: '事件压制',
      tone: 'warning',
      summary: '宏观事件面对这类方向不友好，综合层会先降权，再决定是否保留观察。',
    };
  }

  if (pick.themeIntensity === '高热主线' && pick.compositeScore >= 76) {
    return {
      verdict: '主线共振',
      tone: 'success',
      summary: '事件、资金和策略已经进入同一方向，这类票优先级应该高于普通推荐。',
    };
  }

  if (pick.compositeScore >= 74) {
    return {
      verdict: '综合优先',
      tone: 'success',
      summary: '综合评分已经进入进攻区间，适合先打首仓再看确认。',
    };
  }

  if (pick.compositeScore >= 66) {
    return {
      verdict: '重点观察',
      tone: 'info',
      summary: '不是最强共振，但已经值得放到第一批观察名单。',
    };
  }

  return {
    verdict: '备选观察',
    tone: 'warning',
    summary: '这条更适合留在影子候选池里，等待主线和量能继续确认。',
  };
}

function canOpenCompositeDetail(pick: CompositePick | null): boolean {
  return Boolean(pick && pick.sourceCategory !== 'theme_seed' && !pick.signalId.startsWith('theme-seed-'));
}

async function loadSignalsScreen(token?: string): Promise<{
  signals: Signal[];
  compositePicks: CompositePick[];
}> {
  const [signals, compositePicks] = await Promise.all([
    getSignals(token),
    getCompositePicks(token),
  ]);

  return { signals, compositePicks };
}

export default function SignalsScreen() {
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const router = useRouter();
  const { token } = useAuth();
  const { apiBaseUrl } = useRuntimeConfig();
  const { data, error, isPending, refreshing, refresh } = useRemoteResource(
    () => loadSignalsScreen(token ?? undefined),
    [token, apiBaseUrl]
  );
  const signals = data?.signals ?? [];
  const compositePicks = data?.compositePicks ?? [];
  const focusSignal = signals[0] ?? null;
  const focusRecommendation = focusSignal ? buildRecommendation(focusSignal) : null;
  const focusComposite = compositePicks[0] ?? null;
  const focusCompositeRecommendation = focusComposite ? buildCompositeRecommendation(focusComposite) : null;

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <SectionHeading title="推荐" />

      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在拉取推荐列表" />

      <SurfaceCard style={styles.noticeCard}>
        <Text style={[styles.noticeTitle, { color: palette.text }]}>
          {focusSignal ? `${focusSignal.code} ${focusSignal.name}` : '当前没有新的高质量推荐'}
        </Text>
        <Text style={[styles.noticeCopy, { color: palette.subtext }]}>
          {focusSignal
            ? `${focusRecommendation?.summary} ${focusRecommendation?.actionHint}`
            : '今天没有新的强推荐时，这里只保留主推荐结果，不再铺满解释卡。'}
        </Text>
      </SurfaceCard>

      {compositePicks.length > 0 ? (
        <>
          <SectionHeading title="综合推荐榜" />
          <SurfaceCard style={styles.compositeCard}>
            <View style={styles.focusHead}>
              <View style={styles.focusTitleWrap}>
                <Text style={[styles.focusCode, { color: palette.text }]}>
                  {focusComposite?.code} {focusComposite?.name}
                </Text>
                <Text style={[styles.focusMeta, { color: palette.subtext }]}>
                  {focusComposite?.themeSector
                    ? `${focusComposite.themeSector} / `
                    : ''}
                  {focusComposite?.sourceLabel ?? '策略候选'} / {formatTimestamp(focusComposite?.timestamp ?? '')} / 建议首仓{' '}
                  {focusComposite?.firstPositionPct ?? 0}%
                </Text>
                <Text style={[styles.focusMeta, { color: palette.text }]}>
                  {focusCompositeRecommendation?.verdict ?? '综合观察'}
                </Text>
              </View>
            </View>
            <Text style={[styles.focusSummary, { color: palette.text }]}>
              {focusCompositeRecommendation?.summary}
            </Text>
            <Text style={[styles.hintText, { color: palette.subtext }]}>
              综合分 {focusComposite?.compositeScore.toFixed(1) ?? '--'} / 事件分 {focusComposite?.eventScore.toFixed(1) ?? '--'} / {focusComposite?.action}
            </Text>

            <View style={styles.actionRow}>
              <Pressable
                onPress={() => {
                  if (!focusComposite) {
                    return;
                  }
                  if (canOpenCompositeDetail(focusComposite)) {
                    router.push({ pathname: '/signal/[id]', params: { id: focusComposite.signalId } });
                    return;
                  }
                  router.push('/(tabs)/brain');
                }}
                style={[styles.primaryAction, { backgroundColor: palette.tint }]}>
                <Text style={styles.primaryActionText}>
                  {canOpenCompositeDetail(focusComposite) ? '看综合详情锚点' : '去决策台复核'}
                </Text>
              </Pressable>
            </View>
          </SurfaceCard>

        </>
      ) : null}

      {signals.length === 0 && !error ? (
        <SurfaceCard style={styles.noticeCard}>
          <Text style={[styles.noticeTitle, { color: palette.text }]}>当前没有推荐</Text>
          <Text style={[styles.noticeCopy, { color: palette.subtext }]}>
            先去决策台手动诊股，或者等下一次策略触发。
          </Text>
        </SurfaceCard>
      ) : null}

      {compositePicks.length === 0 && focusSignal && focusRecommendation ? (
        <>
          <SectionHeading title="今日焦点推荐" />
          <SurfaceCard style={styles.focusCard}>
            <View style={styles.focusHead}>
              <View style={styles.focusTitleWrap}>
                <Text style={[styles.focusCode, { color: palette.text }]}>
                  {focusSignal.code} {focusSignal.name}
                </Text>
                <Text style={[styles.focusMeta, { color: palette.subtext }]}>
                  {formatTimestamp(focusSignal.timestamp)} / 现价 {focusSignal.price.toFixed(2)} / 涨跌{' '}
                  {formatPercent(focusSignal.changePct / 100)}
                </Text>
                <Text style={[styles.focusMeta, { color: palette.text }]}>
                  {focusRecommendation.verdict}
                </Text>
              </View>
            </View>

            <Text style={[styles.focusSummary, { color: palette.text }]}>{focusRecommendation.summary}</Text>
            <Text style={[styles.hintText, { color: palette.subtext }]}>
              评分 {focusSignal.score.toFixed(3)} / 止损 {focusSignal.stopLoss.toFixed(2)} / 目标 {focusSignal.targetPrice.toFixed(2)} / 盈亏比 {focusSignal.riskReward.toFixed(1)}
            </Text>
            <Text style={[styles.hintText, { color: palette.subtext }]}>{focusRecommendation.riskText}</Text>

            <Pressable
              onPress={() => {
                router.push({ pathname: '/signal/[id]', params: { id: focusSignal.id } });
              }}
              style={[styles.primaryAction, { backgroundColor: palette.tint }]}>
              <Text style={styles.primaryActionText}>看推荐详情</Text>
            </Pressable>
          </SurfaceCard>
        </>
      ) : null}

      {signals.length > 1 ? (
        <>
          <SectionHeading title="推荐队列" />
          {signals.slice(1, 2).map((signal) => {
            const recommendation = buildRecommendation(signal);

            return (
              <SurfaceCard key={signal.id} style={styles.card}>
                <View style={styles.cardHead}>
                  <View style={styles.titleWrap}>
                    <Text style={[styles.code, { color: palette.text }]}>
                      {signal.code} {signal.name}
                    </Text>
                    <Text style={[styles.meta, { color: palette.subtext }]}>
                      {formatTimestamp(signal.timestamp)} / 现价 {signal.price.toFixed(2)} / 涨跌{' '}
                      {formatPercent(signal.changePct / 100)}
                    </Text>
                    <Text style={[styles.meta, { color: palette.text }]}>{recommendation.verdict}</Text>
                  </View>
                </View>

                <Text style={[styles.summaryText, { color: palette.text }]}>{recommendation.summary}</Text>
                <Text style={[styles.hintText, { color: palette.subtext }]}>
                  评分 {signal.score.toFixed(3)} / 止损 {signal.stopLoss.toFixed(2)} / 目标 {signal.targetPrice.toFixed(2)} / {recommendation.actionHint}
                </Text>

                <Pressable
                  onPress={() => {
                    router.push({ pathname: '/signal/[id]', params: { id: signal.id } });
                  }}
                  style={[styles.primaryAction, { backgroundColor: palette.tint }]}>
                  <Text style={styles.primaryActionText}>看详情</Text>
                </Pressable>
              </SurfaceCard>
            );
          })}
        </>
      ) : null}
    </AppScreen>
  );
}

const styles = StyleSheet.create({
  heroCopy: {
    color: '#C8D8EB',
    fontSize: 15,
    lineHeight: 22,
  },
  noticeCard: {
    gap: 12,
  },
  compositeCard: {
    gap: 16,
  },
  noticeTitle: {
    fontSize: 18,
    fontWeight: '800',
    lineHeight: 24,
  },
  noticeCopy: {
    fontSize: 14,
    lineHeight: 22,
  },
  focusCard: {
    gap: 16,
  },
  focusHead: {
    gap: 10,
  },
  focusTitleWrap: {
    gap: 4,
  },
  focusCode: {
    fontSize: 24,
    fontWeight: '800',
    lineHeight: 30,
  },
  focusMeta: {
    fontSize: 13,
    lineHeight: 20,
  },
  focusSummary: {
    fontSize: 16,
    lineHeight: 24,
    fontWeight: '700',
  },
  hintText: {
    fontSize: 13,
    lineHeight: 20,
  },
  actionRow: {
    flexDirection: 'row',
    gap: 10,
  },
  primaryAction: {
    flex: 1,
    borderRadius: 18,
    minHeight: 46,
    paddingHorizontal: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  primaryActionText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '800',
  },
  secondaryAction: {
    borderWidth: 1,
    borderRadius: 18,
    minHeight: 46,
    paddingHorizontal: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  secondaryActionText: {
    fontSize: 14,
    fontWeight: '800',
  },
  card: {
    gap: 14,
  },
  cardHead: {
    gap: 10,
  },
  titleWrap: {
    gap: 4,
  },
  code: {
    fontSize: 20,
    fontWeight: '800',
    lineHeight: 26,
  },
  meta: {
    fontSize: 13,
    lineHeight: 20,
  },
  summaryText: {
    fontSize: 15,
    lineHeight: 22,
    fontWeight: '700',
  },
});
