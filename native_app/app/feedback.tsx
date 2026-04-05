import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors } from '@/constants/theme';
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

      <SectionHeading title="内测意见箱" />

      <SurfaceCard style={styles.sectionCard}>
        <Text style={[styles.contextTitle, { color: palette.text }]}>
          {pendingCount > 0 ? `当前有 ${pendingCount} 条待决策意见` : '当前没有待决策意见'}
        </Text>
        <Text style={[styles.contextBody, { color: palette.subtext }]}>
          待决策 {pendingCount} / {canDecide ? '当前可拍板' : '当前只收集'}
        </Text>
        {feedbackItems[0] ? (
          <Text style={[styles.contextBody, { color: palette.subtext }]}>
            当前焦点：{feedbackItems[0].title}
          </Text>
        ) : null}
      </SurfaceCard>

      {hasSourceContext ? (
        <SurfaceCard style={styles.contextCard}>
          <Text style={[styles.contextBody, { color: palette.subtext }]}>
            来源 {sourceType || 'unknown'}
            {sourceId ? ` / ${sourceId}` : ''}
            {sourceRoute ? ` / ${sourceRoute}` : ''}
          </Text>
        </SurfaceCard>
      ) : null}

      <SurfaceCard style={styles.sectionCard}>
        <Text style={[styles.blockTitle, { color: palette.text }]}>提交意见</Text>
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

      <SectionHeading title="意见列表" />
      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在同步实验意见" />

      {feedbackItems.length === 0 && !error ? (
        <SurfaceCard>
          <Text style={[styles.emptyText, { color: palette.subtext }]}>
            还没有用户意见。等第一批实验用户开始反馈后，这里会按时间倒序显示。
          </Text>
        </SurfaceCard>
      ) : null}

            {feedbackItems.slice(0, 2).map((item) => (
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
              <Text style={[styles.itemMeta, { color: palette.subtext }]}>
                {statusLabel(item.decisionStatus)}
              </Text>
            </View>
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
