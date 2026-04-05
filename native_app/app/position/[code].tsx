import { useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { StatusPill } from '@/components/app/status-pill';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors } from '@/constants/theme';
import { buildActionReceiptHref } from '@/lib/action-receipt';
import { formatCurrency, formatPercent, formatTimestamp } from '@/lib/format';
import { closePosition, getPositionDetail, updatePositionRisk } from '@/lib/api';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRemoteResource } from '@/hooks/use-remote-resource';
import { useAuth } from '@/providers/auth-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';
import type { PositionDetail } from '@/types/trading';

type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

function getStopBufferPct(position: PositionDetail): number | null {
  if (position.currentPrice <= 0 || position.stopLoss <= 0) {
    return null;
  }

  return (position.currentPrice - position.stopLoss) / position.currentPrice;
}

function getTargetGapPct(position: PositionDetail): number | null {
  if (position.currentPrice <= 0 || position.takeProfit <= 0) {
    return null;
  }

  return (position.takeProfit - position.currentPrice) / position.currentPrice;
}

function buildPositionDecision(
  position: PositionDetail
): {
  verdict: string;
  tone: Tone;
  summary: string;
  nextStep: string;
  reasons: string[];
  warnings: string[];
} {
  const stopBufferPct = getStopBufferPct(position);
  const targetGapPct = getTargetGapPct(position);
  const reasons = [
    `当前浮盈亏 ${formatCurrency(position.profitLoss)}，收益率 ${formatPercent(position.profitLossPct / 100)}。`,
    `持有 ${position.holdDays} 天，当前策略是 ${position.strategy}。`,
    `仓位数量 ${position.quantity} 股，现价 ${position.currentPrice.toFixed(2)}。`,
  ];
  const warnings: string[] = [];

  if (stopBufferPct !== null) {
    warnings.push(
      stopBufferPct <= 0
        ? `当前价已经跌破止损 ${position.stopLoss.toFixed(2)}。`
        : `距离止损只剩 ${formatPercent(stopBufferPct)}。`
    );
  } else {
    warnings.push('这笔仓位还没有完整的止损保护，先补纪律。');
  }

  if (targetGapPct !== null && targetGapPct <= 0.03) {
    warnings.push(`距离止盈只剩 ${formatPercent(Math.max(targetGapPct, 0))}，要考虑锁盈。`);
  }

  if (stopBufferPct !== null && stopBufferPct <= 0) {
    return {
      verdict: '优先减仓或平仓',
      tone: 'danger',
      summary: '这笔仓位已经失守，不值得再讨论“要不要等等看”。',
      nextStep: '先执行减仓或平仓，再回头看逻辑是否还成立。',
      reasons,
      warnings,
    };
  }

  if (stopBufferPct !== null && stopBufferPct <= 0.02) {
    return {
      verdict: '接近止损，先降风险',
      tone: 'danger',
      summary: '仓位已经逼近风险线，最该做的是收缩风险而不是继续找理由。',
      nextStep: '先上移风控或者直接减仓，别让亏损仓位变成情绪仓位。',
      reasons,
      warnings,
    };
  }

  if (position.profitLossPct >= 5 && targetGapPct !== null && targetGapPct <= 0.03) {
    return {
      verdict: '接近止盈，适合锁盈',
      tone: 'success',
      summary: '利润已经出来了，现在重点不是赌更高，而是把利润留住。',
      nextStep: '把止损上移到更安全的位置，必要时先减一部分。',
      reasons,
      warnings,
    };
  }

  if (position.profitLossPct >= 3) {
    return {
      verdict: '盈利中，继续拿但要保护',
      tone: 'success',
      summary: '仓位总体健康，可以继续持有，但保护线该跟上了。',
      nextStep: '考虑把止损上移到更接近成本或更低回撤的位置。',
      reasons,
      warnings,
    };
  }

  if (position.profitLossPct < 0) {
    return {
      verdict: '浮亏观察，先看纪律',
      tone: 'warning',
      summary: '现在最容易犯的错不是亏一点，而是因为不甘心而拖到更大。',
      nextStep: '盯住止损线，先决定规则还是否有效，再决定是否继续拿。',
      reasons,
      warnings,
    };
  }

  return {
    verdict: '继续观察',
    tone: 'info',
    summary: '仓位暂时在可控区间，没有必要频繁动它。',
    nextStep: '保持止损和目标位清晰，等下一次明显变化再处理。',
    reasons,
    warnings,
  };
}

function getGuideTone(mode: string, eventBias: string): Tone {
  if (mode.includes('优先减仓') || mode.includes('先降风险')) {
    return 'danger';
  }
  if (mode.includes('锁盈')) {
    return 'success';
  }
  if (eventBias === '偏空' || mode.includes('浮亏')) {
    return 'warning';
  }
  return 'info';
}

function getPositionCallout(position: PositionDetail, decision: ReturnType<typeof buildPositionDecision>): {
  title: string;
  summary: string;
  tone: Tone;
} {
  if (decision.verdict === '优先减仓或平仓' || decision.verdict === '接近止损，先降风险') {
    return {
      title: '当前先降风险',
      summary: '这笔仓位现在最重要的是守纪律，不是再给自己找继续拿的理由。',
      tone: 'danger',
    };
  }

  if (decision.verdict === '接近止盈，适合锁盈' || position.profitLossPct >= 5) {
    return {
      title: '利润出来了，先保护',
      summary: '当前的重点是锁盈和收缩回撤，而不是继续贪更高收益。',
      tone: 'success',
    };
  }

  if (position.profitLossPct < 0) {
    return {
      title: '浮亏阶段，先看纪律',
      summary: '先确认止损线和逻辑是否仍然有效，再决定要不要继续拿。',
      tone: 'warning',
    };
  }

  return {
    title: '仓位暂时可控',
    summary: '仓位仍在可管理区间，现在更适合继续跟踪而不是频繁动作。',
    tone: 'info',
  };
}

export default function PositionDetailScreen() {
  const { code } = useLocalSearchParams<{ code?: string }>();
  const router = useRouter();
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const { token } = useAuth();
  const { apiBaseUrl } = useRuntimeConfig();
  const [stopLossDraft, setStopLossDraft] = useState('');
  const [takeProfitDraft, setTakeProfitDraft] = useState('');
  const [closeQuantityDraft, setCloseQuantityDraft] = useState('');
  const [actionError, setActionError] = useState<string | null>(null);
  const [isSavingRisk, setIsSavingRisk] = useState(false);
  const [isClosing, setIsClosing] = useState(false);
  const { data, error, isPending, refreshing, refresh } = useRemoteResource(
    async () => {
      if (!code) {
        throw new Error('缺少持仓代码');
      }

      const position = await getPositionDetail(code, token ?? undefined);
      return { position };
    },
    [code, token, apiBaseUrl]
  );

  const position = data?.position;
  const decision = position ? buildPositionDecision(position) : null;
  const positionCallout = position && decision ? getPositionCallout(position, decision) : null;
  const guide = position?.positionGuide ?? null;
  const stopBufferPct = position ? getStopBufferPct(position) : null;
  const targetGapPct = position ? getTargetGapPct(position) : null;
  const sellAll = position ? `${position.quantity}` : '';

  useEffect(() => {
    if (!position) {
      return;
    }

    setStopLossDraft(position.stopLoss > 0 ? position.stopLoss.toFixed(2) : '');
    setTakeProfitDraft(position.takeProfit > 0 ? position.takeProfit.toFixed(2) : '');
    setCloseQuantityDraft(`${position.quantity}`);
  }, [position]);

  function parsePriceDraft(value: string, emptyLabel: 'empty'): number | 'empty' | null {
    const trimmed = value.trim();
    if (!trimmed) {
      return emptyLabel;
    }

    const numeric = Number.parseFloat(trimmed);
    if (!Number.isFinite(numeric) || numeric < 0) {
      return null;
    }

    return numeric;
  }

  async function handleSaveRisk() {
    if (!position || !code) {
      return;
    }

    const nextStopLoss = parsePriceDraft(stopLossDraft, 'empty');
    const nextTakeProfit = parsePriceDraft(takeProfitDraft, 'empty');

    if (nextStopLoss === null || nextTakeProfit === null) {
      setActionError('止损和止盈必须是大于等于 0 的数字。');
      return;
    }

    setIsSavingRisk(true);
    setActionError(null);

    try {
      const result = await updatePositionRisk(
        code,
        {
          stopLoss: nextStopLoss === 'empty' ? 0 : nextStopLoss,
          takeProfit: nextTakeProfit === 'empty' ? 0 : nextTakeProfit,
        },
        token ?? undefined
      );
      router.replace(
        buildActionReceiptHref(result, {
          source: 'position',
          positionCode: code,
        })
      );
    } catch (actionErr) {
      setActionError(actionErr instanceof Error ? actionErr.message : '保存风控失败');
    } finally {
      setIsSavingRisk(false);
    }
  }

  async function executeClose(closeQuantity: number) {
    if (!code || !position) {
      return;
    }

    setIsClosing(true);
    setActionError(null);

    try {
      const result = await closePosition(
        code,
        {
          reason: closeQuantity === position.quantity ? '移动端手动平仓' : '移动端部分减仓',
          quantity: closeQuantity,
        },
        token ?? undefined
      );
      router.replace(
        buildActionReceiptHref(result, {
          source: 'position',
          positionCode: code,
        })
      );
    } catch (actionErr) {
      setActionError(actionErr instanceof Error ? actionErr.message : '平仓失败');
    } finally {
      setIsClosing(false);
    }
  }

  function handleClosePress() {
    if (!position) {
      return;
    }

    const closeQuantity = Number.parseInt(closeQuantityDraft, 10);
    if (!Number.isInteger(closeQuantity) || closeQuantity <= 0) {
      setActionError('请输入有效的卖出数量。');
      return;
    }
    if (closeQuantity > position.quantity) {
      setActionError('卖出数量不能超过当前持仓。');
      return;
    }

    const actionLabel = closeQuantity === position.quantity ? '手动平仓' : '部分减仓';
    Alert.alert(`确认${actionLabel}`, `会按当前持仓快照价格卖出 ${closeQuantity} 股。`, [
      {
        text: '取消',
        style: 'cancel',
      },
      {
        text: '确认执行',
        style: 'destructive',
        onPress: () => {
          void executeClose(closeQuantity);
        },
      },
    ]);
  }

  function tradeTypeLabel(type: string) {
    if (type === 'buy') {
      return '买入';
    }
    if (type === 'sell') {
      return '卖出';
    }
    if (type === 'adjust') {
      return '风控调整';
    }
    return type || '未分类';
  }

  function applyBreakEvenStop() {
    if (!position) {
      return;
    }

    setStopLossDraft(position.costPrice.toFixed(2));
  }

  function applySuggestedStopLoss() {
    if (!guide || guide.suggestedStopLoss <= 0) {
      return;
    }
    setStopLossDraft(guide.suggestedStopLoss.toFixed(2));
  }

  function setCloseFraction(fraction: number) {
    if (!position) {
      return;
    }

    const nextQuantity = Math.max(1, Math.floor(position.quantity * fraction / 100) * 100);
    setCloseQuantityDraft(String(Math.min(position.quantity, nextQuantity)));
  }

  function applySuggestedReduction() {
    if (!guide || guide.suggestedReduceQuantity <= 0) {
      return;
    }
    setCloseQuantityDraft(String(Math.min(position?.quantity ?? guide.suggestedReduceQuantity, guide.suggestedReduceQuantity)));
  }

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <Pressable
        onPress={() => {
          router.back();
        }}
        style={styles.backButton}>
        <Text style={[styles.backText, { color: palette.tint }]}>返回持仓列表</Text>
      </Pressable>
      <SurfaceCard style={styles.sectionCard}>
        <View style={styles.summaryHeader}>
          <View style={styles.summaryCopy}>
            <Text style={[styles.summaryTitle, { color: palette.text }]}>
              {position?.code ?? '--'} {position?.name ?? ''}
            </Text>
            <Text style={[styles.summaryText, { color: palette.subtext }]}>
              {positionCallout?.summary ?? decision?.summary ?? '先看结论和纪律，再决定要不要动。'}
            </Text>
          </View>
          <StatusPill label={decision?.verdict ?? '等待数据'} tone={decision?.tone ?? 'neutral'} />
        </View>
        {position ? (
          <View style={styles.summaryPills}>
            {guide ? (
              <StatusPill label={guide.mode} tone={getGuideTone(guide.mode, guide.eventBias)} />
            ) : null}
            <StatusPill
              label={formatPercent(position.profitLossPct / 100)}
              tone={position.profitLossPct >= 0 ? 'success' : 'warning'}
            />
            <StatusPill label={`持有 ${position.holdDays} 天`} tone="info" />
          </View>
        ) : null}
        {decision?.nextStep ? (
          <Text style={[styles.summaryHint, { color: palette.subtext }]}>{decision.nextStep}</Text>
        ) : null}
      </SurfaceCard>

      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在读取持仓详情" />

      {position && decision ? (
        <>
          <SectionHeading title="持仓结论" />
          <SurfaceCard style={styles.sectionCard}>
            <View style={styles.summaryHeader}>
              <View style={styles.summaryCopy}>
                <Text style={[styles.summaryTitle, { color: palette.text }]}>{decision.verdict}</Text>
                <Text style={[styles.summaryText, { color: palette.subtext }]}>{decision.summary}</Text>
              </View>
              <StatusPill
                label={formatCurrency(position.profitLoss)}
                tone={position.profitLoss >= 0 ? 'success' : 'warning'}
              />
            </View>

            <Text style={[styles.summaryHint, { color: palette.text }]}>{decision.nextStep}</Text>
            <Text style={[styles.summaryHint, { color: palette.subtext }]}>{decision.reasons[0]}</Text>

            {guide ? (
              <>
                <View style={styles.rowBetween}>
                  <Text style={[styles.rowLabel, { color: palette.subtext }]}>组合纪律</Text>
                  <Text style={[styles.rowValue, { color: palette.text }]}>{guide.mode}</Text>
                </View>
                <View style={styles.rowBetween}>
                  <Text style={[styles.rowLabel, { color: palette.subtext }]}>总仓 / 单票</Text>
                  <Text style={[styles.rowValue, { color: palette.text }]}>
                    {guide.currentExposurePct.toFixed(1)}% / {guide.positionPct.toFixed(1)}%
                  </Text>
                </View>
                <View style={styles.rowBetween}>
                  <Text style={[styles.rowLabel, { color: palette.subtext }]}>主题占比</Text>
                  <Text style={[styles.rowValue, { color: palette.text }]}>
                    {guide.currentThemeExposurePct.toFixed(1)}% / {guide.maxThemeExposurePct}%
                  </Text>
                </View>
                <Text style={[styles.summaryHint, { color: palette.subtext }]}>
                  {guide.nextAction}
                  {guide.warnings[0] ? ` ${guide.warnings[0]}` : ''}
                </Text>
              </>
            ) : null}
          </SurfaceCard>

          <SectionHeading title="风险边界" />
          <SurfaceCard style={styles.sectionCard}>
            <View style={styles.rowBetween}>
              <Text style={[styles.rowLabel, { color: palette.subtext }]}>现价 / 成本</Text>
              <Text style={[styles.rowValue, { color: palette.text }]}>
                {position.currentPrice.toFixed(2)} / {position.costPrice.toFixed(2)}
              </Text>
            </View>
            <View style={styles.rowBetween}>
              <Text style={[styles.rowLabel, { color: palette.subtext }]}>止损 / 止盈</Text>
              <Text style={[styles.rowValue, { color: palette.text }]}>
                {position.stopLoss.toFixed(2)} / {position.takeProfit > 0 ? position.takeProfit.toFixed(2) : '未设置'}
              </Text>
            </View>
            <View style={styles.rowBetween}>
              <Text style={[styles.rowLabel, { color: palette.subtext }]}>距离止损 / 止盈</Text>
              <Text style={[styles.rowValue, { color: palette.text }]}>
                {stopBufferPct === null ? '--' : formatPercent(stopBufferPct)} / {targetGapPct === null ? '--' : formatPercent(targetGapPct)}
              </Text>
            </View>
            <View style={styles.rowBetween}>
              <Text style={[styles.rowLabel, { color: palette.subtext }]}>持有 / 追踪止盈</Text>
              <Text style={[styles.rowValue, { color: palette.text }]}>
                {position.holdDays} 天 / {position.trailingStop ? `已启用 ${position.trailingTriggerPrice.toFixed(2)}` : '未启用'}
              </Text>
            </View>
            <View style={styles.formBlock}>
              <Text style={[styles.inputLabel, { color: palette.subtext }]}>快速动作</Text>
              <View style={styles.presetRow}>
                {guide?.suggestedStopLoss ? (
                  <Pressable
                    onPress={applySuggestedStopLoss}
                    style={[styles.presetChip, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
                    <Text style={[styles.presetChipText, { color: palette.text }]}>建议止损</Text>
                  </Pressable>
                ) : null}
                <Pressable
                  onPress={applyBreakEvenStop}
                  style={[styles.presetChip, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
                  <Text style={[styles.presetChipText, { color: palette.text }]}>止损到保本</Text>
                </Pressable>
              </View>
            </View>

            <View style={styles.formBlock}>
              <Text style={[styles.inputLabel, { color: palette.subtext }]}>止损价</Text>
              <TextInput
                keyboardType="decimal-pad"
                onChangeText={setStopLossDraft}
                placeholder="留空表示清空"
                placeholderTextColor={palette.icon}
                style={[
                  styles.input,
                  {
                    backgroundColor: palette.surfaceMuted,
                    borderColor: palette.border,
                    color: palette.text,
                  },
                ]}
                value={stopLossDraft}
              />
            </View>

            <View style={styles.formBlock}>
              <Text style={[styles.inputLabel, { color: palette.subtext }]}>止盈价</Text>
              <TextInput
                keyboardType="decimal-pad"
                onChangeText={setTakeProfitDraft}
                placeholder="留空表示清空"
                placeholderTextColor={palette.icon}
                style={[
                  styles.input,
                  {
                    backgroundColor: palette.surfaceMuted,
                    borderColor: palette.border,
                    color: palette.text,
                  },
                ]}
                value={takeProfitDraft}
              />
            </View>

            <View style={styles.formBlock}>
              <Text style={[styles.inputLabel, { color: palette.subtext }]}>卖出数量</Text>
              <View style={styles.presetRow}>
                {guide && guide.suggestedReduceQuantity > 0 ? (
                  <Pressable
                    onPress={applySuggestedReduction}
                    style={[styles.presetChip, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
                    <Text style={[styles.presetChipText, { color: palette.text }]}>
                      建议减 {guide.suggestedReducePct >= 100 ? '全部' : `${guide.suggestedReducePct}%`}
                    </Text>
                  </Pressable>
                ) : null}
                <Pressable
                  onPress={() => {
                    setCloseFraction(50);
                  }}
                  style={[styles.presetChip, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
                  <Text style={[styles.presetChipText, { color: palette.text }]}>减半</Text>
                </Pressable>
                <Pressable
                  onPress={() => {
                    setCloseQuantityDraft(sellAll);
                  }}
                  style={[styles.presetChip, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
                  <Text style={[styles.presetChipText, { color: palette.text }]}>全部卖出</Text>
                </Pressable>
              </View>
              <TextInput
                keyboardType="number-pad"
                onChangeText={setCloseQuantityDraft}
                placeholder={`${position.quantity}`}
                placeholderTextColor={palette.icon}
                style={[
                  styles.input,
                  {
                    backgroundColor: palette.surfaceMuted,
                    borderColor: palette.border,
                    color: palette.text,
                  },
                ]}
                value={closeQuantityDraft}
              />
            </View>

            {guide ? (
              <Text style={[styles.summaryHint, { color: palette.subtext }]}>
                {guide.canAdd
                  ? '当前仍可观察后加仓，但前提是先把保护线设好。'
                  : '当前不建议加仓，先按减仓、锁盈或收缩风险的动作走。'}
              </Text>
            ) : null}

            <View style={styles.buttonRow}>
              <Pressable
                disabled={isSavingRisk}
                onPress={() => {
                  void handleSaveRisk();
                }}
                style={[
                  styles.primaryButton,
                  { backgroundColor: isSavingRisk ? palette.icon : palette.tint },
                ]}>
                {isSavingRisk ? (
                  <ActivityIndicator color="#FFFFFF" />
                ) : (
                  <Text style={styles.primaryButtonText}>保存风控</Text>
                )}
              </Pressable>
              <Pressable
                disabled={isClosing}
                onPress={handleClosePress}
                style={[
                  styles.secondaryButton,
                  {
                    backgroundColor: palette.surface,
                    borderColor: palette.danger,
                    opacity: isClosing ? 0.7 : 1,
                  },
                ]}>
                {isClosing ? (
                  <ActivityIndicator color={palette.danger} />
                ) : (
                  <Text style={[styles.secondaryButtonText, { color: palette.danger }]}>
                    减仓 / 平仓
                  </Text>
                )}
              </Pressable>
            </View>
            {actionError ? (
              <Text style={[styles.feedbackText, { color: palette.danger }]}>{actionError}</Text>
            ) : null}
          </SurfaceCard>

          <SectionHeading title="交易记录" />
          <SurfaceCard style={styles.sectionCard}>
            {position.trades.length === 0 ? (
              <Text style={[styles.emptyText, { color: palette.subtext }]}>当前没有交易记录。</Text>
            ) : (
              position.trades.slice(0, 2).map((trade) => (
                <View key={`${trade.time}-${trade.type}`} style={styles.tradeRow}>
                  <View style={styles.tradeMain}>
                    <Text style={[styles.tradeType, { color: palette.text }]}>{tradeTypeLabel(trade.type)}</Text>
                    <Text style={[styles.tradeReason, { color: palette.subtext }]}>{trade.reason}</Text>
                  </View>
                  <View style={styles.tradeMeta}>
                    <Text style={[styles.tradePrice, { color: palette.text }]}>
                      {trade.price.toFixed(2)} x {trade.quantity}
                    </Text>
                    <Text style={[styles.tradeReason, { color: palette.subtext }]}>
                      {formatTimestamp(trade.time.replace(' ', 'T'))}
                    </Text>
                  </View>
                </View>
              ))
            )}
          </SurfaceCard>
        </>
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
  summaryPills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  summaryHint: {
    fontSize: 13,
    lineHeight: 20,
  },
  sectionCard: {
    gap: 14,
  },
  summaryHeader: {
    gap: 12,
  },
  summaryCopy: {
    gap: 6,
  },
  summaryTitle: {
    fontSize: 22,
    fontWeight: '800',
    lineHeight: 30,
  },
  summaryText: {
    fontSize: 15,
    lineHeight: 22,
  },
  insightBox: {
    borderRadius: 18,
    padding: 14,
    gap: 6,
  },
  insightTitle: {
    fontSize: 14,
    fontWeight: '800',
  },
  insightText: {
    fontSize: 14,
    lineHeight: 22,
  },
  listGroup: {
    gap: 8,
  },
  listHeading: {
    fontSize: 15,
    fontWeight: '800',
  },
  listRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 999,
    marginTop: 7,
  },
  listText: {
    flex: 1,
    fontSize: 14,
    lineHeight: 22,
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
    lineHeight: 20,
    textAlign: 'right',
  },
  formBlock: {
    gap: 8,
  },
  inputLabel: {
    fontSize: 13,
    fontWeight: '700',
  },
  presetRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  presetChip: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  presetChipText: {
    fontSize: 13,
    fontWeight: '700',
  },
  input: {
    borderWidth: 1,
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
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
  secondaryButton: {
    flex: 1,
    minHeight: 48,
    borderRadius: 16,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 18,
  },
  secondaryButtonText: {
    fontSize: 15,
    fontWeight: '800',
  },
  feedbackText: {
    fontSize: 13,
    lineHeight: 20,
  },
  emptyText: {
    fontSize: 14,
    lineHeight: 22,
  },
  tradeRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    paddingVertical: 10,
  },
  tradeMain: {
    flex: 1,
    gap: 4,
  },
  tradeMeta: {
    alignItems: 'flex-end',
    gap: 4,
  },
  tradeType: {
    fontSize: 15,
    fontWeight: '700',
  },
  tradePrice: {
    fontSize: 14,
    fontWeight: '700',
  },
  tradeReason: {
    fontSize: 13,
    lineHeight: 18,
  },
});
