import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { ExecutiveSummaryGrid } from '@/components/app/executive-summary-grid';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { StatusPill } from '@/components/app/status-pill';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors, Spacing } from '@/constants/theme';
import { decideFeedback, getFeedbackItems, submitFeedback } from '@/lib/api';
import { formatTimestamp } from '@/lib/format';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRemoteResource } from '@/hooks/use-remote-resource';
import { useAuth } from '@/providers/auth-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';
import type { FeedbackItem } from '@/types/trading';

const categoryOptions = [
  { value: 'ux', label: '体验' },
  { value: 'strategy', label: '策略' },
  { value: 'risk', label: '风控' },
  { value: 'bug', label: 'Bug' },
];

const priorityOptions = [
  { value: 'low', label: '低' },
  { value: 'medium', label: '中' },
  { value: 'high', label: '高' },
];

function statusTone(status: string): 'neutral' | 'info' | 'success' | 'warning' {
  if (status === 'accepted') {
    return 'success';
  }
  if (status === 'watchlist') {
    return 'info';
  }
  if (status === 'rejected') {
    return 'neutral';
  }
  return 'warning';
}

function statusLabel(status: string) {
  if (status === 'accepted') {
    return '已采纳';
  }
  if (status === 'watchlist') {
    return '待观察';
  }
  if (status === 'rejected') {
    return '不采纳';
  }
  return '待决策';
}

function priorityLabel(priority: string) {
  if (priority === 'high') {
    return '高优先级';
  }
  if (priority === 'low') {
    return '低优先级';
  }
  return '中优先级';
}

function decisionNote(decision: 'pending' | 'watchlist' | 'accepted' | 'rejected') {
  if (decision === 'accepted') {
    return '创始人决定进入需求池。';
  }
  if (decision === 'rejected') {
    return '创始人决定本轮不采纳。';
  }
  if (decision === 'watchlist') {
    return '创始人决定先观察，不立即进入开发。';
  }
  return '重新退回待决策。';
}

function FeedbackDecisionButtons({
  item,
  busyId,
  onDecision,
}: {
  item: FeedbackItem;
  busyId: string | null;
  onDecision: (item: FeedbackItem, decision: 'pending' | 'watchlist' | 'accepted' | 'rejected') => void;
}) {
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const busy = busyId === item.id;

  if (item.decisionStatus === 'accepted' || item.decisionStatus === 'rejected') {
    return (
      <Pressable
        disabled={busy}
        onPress={() => {
          onDecision(item, 'pending');
        }}
        style={[styles.ghostButton, { borderColor: palette.border, opacity: busy ? 0.7 : 1 }]}>
        {busy ? (
          <ActivityIndicator color={palette.text} />
        ) : (
          <Text style={[styles.ghostButtonText, { color: palette.text }]}>退回待决策</Text>
        )}
      </Pressable>
    );
  }

  return (
    <View style={styles.buttonRow}>
      <Pressable
        disabled={busy}
        onPress={() => {
          onDecision(item, 'watchlist');
        }}
        style={[styles.ghostButton, { borderColor: palette.border, flex: 1, opacity: busy ? 0.7 : 1 }]}>
        <Text style={[styles.ghostButtonText, { color: palette.text }]}>待观察</Text>
      </Pressable>
      <Pressable
        disabled={busy}
        onPress={() => {
          onDecision(item, 'accepted');
        }}
        style={[styles.successButton, { backgroundColor: palette.success, opacity: busy ? 0.7 : 1 }]}>
        <Text style={styles.primaryButtonText}>采纳</Text>
      </Pressable>
      <Pressable
        disabled={busy}
        onPress={() => {
          onDecision(item, 'rejected');
        }}
        style={[styles.rejectButton, { backgroundColor: palette.danger, opacity: busy ? 0.7 : 1 }]}>
        <Text style={styles.primaryButtonText}>不采纳</Text>
      </Pressable>
    </View>
  );
}

export default function FeedbackScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{
    title?: string;
    message?: string;
    category?: string;
    sourceType?: string;
    sourceId?: string;
    sourceRoute?: string;
  }>();
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const { token, user } = useAuth();
  const { apiBaseUrl } = useRuntimeConfig();
  const [titleDraft, setTitleDraft] = useState('');
  const [messageDraft, setMessageDraft] = useState('');
  const [category, setCategory] = useState('ux');
  const [priority, setPriority] = useState('medium');
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [decisionBusyId, setDecisionBusyId] = useState<string | null>(null);
  const { data, error, isPending, refreshing, refresh } = useRemoteResource(
    () => getFeedbackItems(token ?? undefined),
    [token, apiBaseUrl]
  );

  const feedbackItems = data ?? [];
  const pendingCount = feedbackItems.filter((item) => item.decisionStatus === 'pending').length;
  const watchlistCount = feedbackItems.filter((item) => item.decisionStatus === 'watchlist').length;
  const canDecide = user?.role === 'operator';
  const sourceType = typeof params.sourceType === 'string' ? params.sourceType : '';
  const sourceId = typeof params.sourceId === 'string' ? params.sourceId : '';
  const sourceRoute = typeof params.sourceRoute === 'string' ? params.sourceRoute : '';
  const hasSourceContext = Boolean(sourceType || sourceId || sourceRoute);

  useEffect(() => {
    if (typeof params.title === 'string' && params.title && !titleDraft) {
      setTitleDraft(params.title);
    }
    if (typeof params.message === 'string' && params.message && !messageDraft) {
      setMessageDraft(params.message);
    }
    if (typeof params.category === 'string' && params.category) {
      setCategory(params.category);
    }
  }, [messageDraft, params.category, params.message, params.title, titleDraft]);

  async function handleSubmit() {
    if (!titleDraft.trim()) {
      setActionSuccess(null);
      setActionError('请先写一个意见标题。');
      return;
    }
    if (!messageDraft.trim()) {
      setActionSuccess(null);
      setActionError('请先写清楚意见内容。');
      return;
    }

    setIsSubmitting(true);
    setActionError(null);
    setActionSuccess(null);

    try {
      const result = await submitFeedback(
        {
          title: titleDraft.trim(),
          message: messageDraft.trim(),
          category,
          priority,
          sourceType,
          sourceId,
          sourceRoute,
        },
        token ?? undefined
      );
      setTitleDraft('');
      setMessageDraft('');
      setCategory('ux');
      setPriority('medium');
      setActionSuccess(result.message);
      await refresh();
    } catch (submitError) {
      setActionError(submitError instanceof Error ? submitError.message : '提交意见失败');
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleDecision(
    item: FeedbackItem,
    decision: 'pending' | 'watchlist' | 'accepted' | 'rejected'
  ) {
    setDecisionBusyId(item.id);
    setActionError(null);
    setActionSuccess(null);

    try {
      const result = await decideFeedback(
        item.id,
        {
          decision,
          ownerNote: decisionNote(decision),
        },
        token ?? undefined
      );
      setActionSuccess(result.message);
      await refresh();
    } catch (decisionError) {
      setActionError(decisionError instanceof Error ? decisionError.message : '更新决策失败');
    } finally {
      setDecisionBusyId(null);
    }
  }

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <Pressable
        onPress={() => {
          router.back();
        }}
        style={styles.backButton}>
        <Text style={[styles.backText, { color: palette.tint }]}>返回我的</Text>
      </Pressable>

      <SectionHeading
        eyebrow="Pilot Feedback"
        title="内测意见箱"
        subtitle="这里收集真实使用意见，但不会自动改产品。进入不进入需求池，只由你亲自决策。"
      />

      <View style={[styles.hero, { backgroundColor: palette.hero }]}>
        <Text style={styles.heroEyebrow}>PILOT FEEDBACK</Text>
        <Text style={styles.heroTitle}>
          {pendingCount > 0 ? `当前有 ${pendingCount} 条待决策意见` : '当前没有待决策意见'}
        </Text>
        <Text style={styles.heroCopy}>
          这页只负责收集、整理和辅助决策，不负责自动改产品。最终采纳权始终在你手里。
        </Text>
      </View>

      <SurfaceCard style={styles.contextCard}>
        <Text style={[styles.contextTitle, { color: palette.text }]}>这页怎么讲</Text>
        <Text style={[styles.contextBody, { color: palette.subtext }]}>
          先强调这是小范围内测收集窗，不是社区。用户能提意见，但系统不会自动采纳，最终拍板只在你手里。
        </Text>
      </SurfaceCard>

      <View style={styles.pillRow}>
        <StatusPill label="小范围实验" tone="info" />
        <StatusPill label="只收集不自动改产品" tone="warning" />
        <StatusPill label="最终决策权在你" tone="success" />
      </View>

      <View style={styles.metricsRow}>
        <SurfaceCard style={styles.metricCard}>
          <Text style={[styles.metricLabel, { color: palette.subtext }]}>待你决策</Text>
          <Text style={[styles.metricValue, { color: palette.text }]}>{pendingCount}</Text>
        </SurfaceCard>
        <SurfaceCard style={styles.metricCard}>
          <Text style={[styles.metricLabel, { color: palette.subtext }]}>保留观察</Text>
          <Text style={[styles.metricValue, { color: palette.text }]}>{watchlistCount}</Text>
        </SurfaceCard>
      </View>

      <SectionHeading
        title="一页反馈判断"
        subtitle="先把反馈规模、当前焦点和决策原则压成一页，再往下看具体意见。"
      />
      <SurfaceCard style={styles.sectionCard}>
        <ExecutiveSummaryGrid
          items={[
            {
              key: 'feedback-scale',
              step: '01 当前规模',
              title: `${feedbackItems.length} 条意见`,
              meta: `待决策 ${pendingCount} / 保留观察 ${watchlistCount}`,
              body: '这里只收真实使用意见，不会自动转成开发任务。',
            },
            {
              key: 'feedback-focus',
              step: '02 当前焦点',
              title: feedbackItems[0]?.title ?? '当前暂无新意见',
              meta: feedbackItems[0]
                ? `${feedbackItems[0].category} / ${priorityLabel(feedbackItems[0].priority)} / ${statusLabel(feedbackItems[0].decisionStatus)}`
                : '等待第一批实验反馈',
              body: feedbackItems[0]?.message ?? '提交后的意见会按时间顺序排进这里，等你亲自决策。',
            },
            {
              key: 'feedback-rule',
              step: '03 决策原则',
              title: canDecide ? '当前账号可直接拍板' : '当前账号只能收集',
              meta: canDecide ? 'operator 账号可采纳、观察或不采纳' : '需切换决策账号处理',
              body: '用户可以提，系统可以排，但是否进入需求池，必须由你亲自决定。',
            },
          ]}
        />
      </SurfaceCard>

      {hasSourceContext ? (
        <SurfaceCard style={styles.contextCard}>
          <Text style={[styles.contextTitle, { color: palette.text }]}>当前意见带上下文</Text>
          <Text style={[styles.contextBody, { color: palette.subtext }]}>
            来源 {sourceType || 'unknown'}
            {sourceId ? ` / ${sourceId}` : ''}
            {sourceRoute ? ` / ${sourceRoute}` : ''}
          </Text>
          <Text style={[styles.contextBody, { color: palette.subtext }]}>
            这样你后面看反馈时，能直接知道它是在什么页面、什么信号或什么持仓里提出来的。
          </Text>
        </SurfaceCard>
      ) : null}

      <SurfaceCard style={styles.sectionCard}>
        <Text style={[styles.blockTitle, { color: palette.text }]}>提交意见</Text>
        <Text style={[styles.contextBody, { color: palette.subtext }]}>
          建议优先写清楚具体页面、问题场景和期待结果。这样你后面做决策时不需要再猜。
        </Text>
        <TextInput
          onChangeText={setTitleDraft}
          placeholder="一句话概括这条意见"
          placeholderTextColor={palette.icon}
          style={[
            styles.input,
            {
              backgroundColor: palette.surfaceMuted,
              borderColor: palette.border,
              color: palette.text,
            },
          ]}
          value={titleDraft}
        />
        <TextInput
          multiline
          onChangeText={setMessageDraft}
          placeholder="把问题、场景、预期结果写清楚"
          placeholderTextColor={palette.icon}
          style={[
            styles.textarea,
            {
              backgroundColor: palette.surfaceMuted,
              borderColor: palette.border,
              color: palette.text,
            },
          ]}
          textAlignVertical="top"
          value={messageDraft}
        />

        <View style={styles.optionBlock}>
          <Text style={[styles.optionLabel, { color: palette.subtext }]}>类别</Text>
          <View style={styles.optionRow}>
            {categoryOptions.map((item) => {
              const active = category === item.value;
              return (
                <Pressable
                  key={item.value}
                  onPress={() => {
                    setCategory(item.value);
                  }}
                  style={[
                    styles.optionChip,
                    {
                      backgroundColor: active ? palette.accentSoft : palette.surface,
                      borderColor: active ? palette.tint : palette.border,
                    },
                  ]}>
                  <Text style={[styles.optionChipText, { color: active ? palette.tint : palette.text }]}>
                    {item.label}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </View>

        <View style={styles.optionBlock}>
          <Text style={[styles.optionLabel, { color: palette.subtext }]}>优先级</Text>
          <View style={styles.optionRow}>
            {priorityOptions.map((item) => {
              const active = priority === item.value;
              return (
                <Pressable
                  key={item.value}
                  onPress={() => {
                    setPriority(item.value);
                  }}
                  style={[
                    styles.optionChip,
                    {
                      backgroundColor: active ? palette.accentSoft : palette.surface,
                      borderColor: active ? palette.tint : palette.border,
                    },
                  ]}>
                  <Text style={[styles.optionChipText, { color: active ? palette.tint : palette.text }]}>
                    {item.label}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </View>

        <Pressable
          disabled={isSubmitting}
          onPress={() => {
            void handleSubmit();
          }}
          style={[styles.primaryButton, { backgroundColor: isSubmitting ? palette.icon : palette.tint }]}>
          {isSubmitting ? (
            <ActivityIndicator color="#FFFFFF" />
          ) : (
            <Text style={styles.primaryButtonText}>提交到意见箱</Text>
          )}
        </Pressable>
        {actionError ? (
          <Text style={[styles.feedbackText, { color: palette.danger }]}>{actionError}</Text>
        ) : null}
        {actionSuccess ? (
          <Text style={[styles.feedbackText, { color: palette.success }]}>{actionSuccess}</Text>
        ) : null}
      </SurfaceCard>

      <SectionHeading title="意见列表" subtitle="系统只负责排队，状态变化必须由你亲自点按钮。" />
      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在同步实验意见" />

      {feedbackItems.length === 0 && !error ? (
        <SurfaceCard>
          <Text style={[styles.emptyText, { color: palette.subtext }]}>
            还没有用户意见。等第一批实验用户开始反馈后，这里会按时间倒序显示。
          </Text>
        </SurfaceCard>
      ) : null}

      {feedbackItems.map((item) => (
        <SurfaceCard key={item.id} style={styles.sectionCard}>
          <View style={styles.rowBetween}>
            <View style={styles.itemMain}>
              <Text style={[styles.itemTitle, { color: palette.text }]}>{item.title}</Text>
              <Text style={[styles.itemMeta, { color: palette.subtext }]}>
                {item.username} · {item.category} · {priorityLabel(item.priority)} ·{' '}
                {formatTimestamp(item.createdAt)}
              </Text>
              {item.sourceType || item.sourceId ? (
                <Text style={[styles.itemMeta, { color: palette.subtext }]}>
                  来源 {item.sourceType || 'unknown'}
                  {item.sourceId ? ` / ${item.sourceId}` : ''}
                </Text>
              ) : null}
            </View>
            <StatusPill label={statusLabel(item.decisionStatus)} tone={statusTone(item.decisionStatus)} />
          </View>

          <Text style={[styles.itemBody, { color: palette.text }]}>{item.message}</Text>

          {item.ownerNote ? (
            <View style={[styles.noteWrap, { backgroundColor: palette.surfaceMuted }]}>
              <Text style={[styles.noteTitle, { color: palette.text }]}>决策备注</Text>
              <Text style={[styles.noteBody, { color: palette.subtext }]}>{item.ownerNote}</Text>
            </View>
          ) : null}

          {canDecide ? (
            <FeedbackDecisionButtons item={item} busyId={decisionBusyId} onDecision={handleDecision} />
          ) : (
            <Text style={[styles.itemMeta, { color: palette.subtext }]}>
              已提交到实验收集箱，等待决策账号处理。
            </Text>
          )}
        </SurfaceCard>
      ))}
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
  pillRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  metricsRow: {
    flexDirection: 'row',
    gap: Spacing.gap,
  },
  metricCard: {
    flex: 1,
    gap: 6,
  },
  contextCard: {
    gap: 6,
  },
  contextTitle: {
    fontSize: 15,
    fontWeight: '800',
  },
  contextBody: {
    fontSize: 13,
    lineHeight: 20,
  },
  metricLabel: {
    fontSize: 12,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
  },
  metricValue: {
    fontSize: 28,
    fontWeight: '800',
  },
  sectionCard: {
    gap: 12,
  },
  blockTitle: {
    fontSize: 18,
    fontWeight: '700',
  },
  input: {
    borderWidth: 1,
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
  },
  textarea: {
    minHeight: 120,
    borderWidth: 1,
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
  },
  optionBlock: {
    gap: 8,
  },
  optionLabel: {
    fontSize: 13,
    fontWeight: '700',
  },
  optionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  optionChip: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  optionChipText: {
    fontSize: 13,
    fontWeight: '700',
  },
  primaryButton: {
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
  feedbackText: {
    fontSize: 13,
    lineHeight: 20,
  },
  rowBetween: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    alignItems: 'flex-start',
  },
  itemMain: {
    flex: 1,
    gap: 4,
  },
  itemTitle: {
    fontSize: 16,
    fontWeight: '800',
  },
  itemMeta: {
    fontSize: 13,
    lineHeight: 19,
  },
  itemBody: {
    fontSize: 14,
    lineHeight: 22,
  },
  noteWrap: {
    borderRadius: 16,
    padding: 12,
    gap: 6,
  },
  noteTitle: {
    fontSize: 13,
    fontWeight: '700',
  },
  noteBody: {
    fontSize: 13,
    lineHeight: 20,
  },
  buttonRow: {
    flexDirection: 'row',
    gap: 10,
  },
  successButton: {
    flex: 1,
    minHeight: 44,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 12,
  },
  rejectButton: {
    flex: 1,
    minHeight: 44,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 12,
  },
  ghostButton: {
    minHeight: 44,
    borderRadius: 14,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 12,
  },
  ghostButtonText: {
    fontSize: 14,
    fontWeight: '700',
  },
  emptyText: {
    fontSize: 14,
    lineHeight: 22,
  },
});
