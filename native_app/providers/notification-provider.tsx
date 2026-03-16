import { PropsWithChildren, createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { AppState, Platform } from 'react-native';
import Constants from 'expo-constants';
import * as Notifications from 'expo-notifications';

import { getStoredValue, setStoredValue } from '@/lib/app-storage';
import { EXPO_PROJECT_ID } from '@/lib/config';
import { getTakeoverPushStatus, registerPushDevice, runTakeoverPushAuto, sendPushTest, sendTakeoverPush } from '@/lib/api';
import type { ActionBoardItem, PushDispatchResult, RiskAlert } from '@/types/trading';
import { useAuth } from '@/providers/auth-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';

const NOTIFIED_ALERT_IDS_KEY = 'alpha-ai-native.notified-alert-ids';
const LAST_TAKEOVER_ACTION_KEY = 'alpha-ai-native.last-takeover-action';
const RISK_ALERT_CHANNEL_ID = 'alpha-ai-native.risk-alerts';
const FOREGROUND_SYNC_DEBOUNCE_MS = 15_000;

type NotificationPermissionState = 'unsupported' | 'undetermined' | 'denied' | 'granted';
type RemotePushState = 'unsupported' | 'idle' | 'syncing' | 'ready' | 'error';

interface NotificationContextValue {
  isSupported: boolean;
  isBooting: boolean;
  permissionState: NotificationPermissionState;
  remotePushState: RemotePushState;
  expoPushToken: string | null;
  lastError: string | null;
  lastDispatchResult: PushDispatchResult | null;
  requestPermission: () => Promise<boolean>;
  sendPreviewNotification: () => Promise<void>;
  registerRemotePush: () => Promise<boolean>;
  sendRemotePreviewNotification: () => Promise<void>;
  sendRemoteTakeoverNotification: () => Promise<void>;
  sendRemoteTakeoverResend: () => Promise<void>;
  sendRemoteTakeoverPreview: () => Promise<void>;
  runRemoteTakeoverAuto: () => Promise<void>;
  pushRiskAlerts: (alerts: RiskAlert[]) => Promise<void>;
  pushTakeoverAction: (actions: ActionBoardItem[]) => Promise<void>;
}

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

const NotificationContext = createContext<NotificationContextValue | null>(null);

function mapPermissionState(
  permission: Awaited<ReturnType<typeof Notifications.getPermissionsAsync>>
): NotificationPermissionState {
  if (
    permission.granted ||
    permission.ios?.status === Notifications.IosAuthorizationStatus.PROVISIONAL
  ) {
    return 'granted';
  }

  if (permission.status === 'denied') {
    return 'denied';
  }

  return 'undetermined';
}

export function NotificationProvider({ children }: PropsWithChildren) {
  const [permissionState, setPermissionState] = useState<NotificationPermissionState>('undetermined');
  const [isBooting, setIsBooting] = useState(true);
  const [lastError, setLastError] = useState<string | null>(null);
  const [lastDispatchResult, setLastDispatchResult] = useState<PushDispatchResult | null>(null);
  const [remotePushState, setRemotePushState] = useState<RemotePushState>('idle');
  const [expoPushToken, setExpoPushToken] = useState<string | null>(null);
  const notifiedAlertIdsRef = useRef<Set<string>>(new Set());
  const lastTakeoverActionRef = useRef<string | null>(null);
  const lastTakeoverAutoCheckRef = useRef<string | null>(null);
  const lastForegroundRefreshAtRef = useRef(0);
  const isSupported = Platform.OS !== 'web';
  const { token, user } = useAuth();
  const { apiBaseUrl } = useRuntimeConfig();

  useEffect(() => {
    let active = true;

    async function bootstrap() {
      if (!isSupported) {
        if (active) {
          setPermissionState('unsupported');
          setRemotePushState('unsupported');
          setIsBooting(false);
        }
        return;
      }

      try {
        if (Platform.OS === 'android') {
          await Notifications.setNotificationChannelAsync(RISK_ALERT_CHANNEL_ID, {
            name: 'Alpha AI 风控提醒',
            importance: Notifications.AndroidImportance.HIGH,
          });
        }

        const storedIds = await getStoredValue(NOTIFIED_ALERT_IDS_KEY);
        notifiedAlertIdsRef.current = storedIds ? new Set(JSON.parse(storedIds) as string[]) : new Set();
        lastTakeoverActionRef.current = await getStoredValue(LAST_TAKEOVER_ACTION_KEY);

        const permission = await Notifications.getPermissionsAsync();
        if (active) {
          setPermissionState(mapPermissionState(permission));
        }
      } catch (error) {
        if (active) {
          setLastError(error instanceof Error ? error.message : '通知初始化失败');
          setPermissionState('denied');
          setRemotePushState('error');
        }
      } finally {
        if (active) {
          setIsBooting(false);
        }
      }
    }

    void bootstrap();

    return () => {
      active = false;
    };
  }, [isSupported]);

  async function requestPermission() {
    if (!isSupported) {
      setPermissionState('unsupported');
      setRemotePushState('unsupported');
      return false;
    }

    try {
      const permission = await Notifications.requestPermissionsAsync({
        ios: {
          allowAlert: true,
          allowBadge: true,
          allowSound: true,
          allowProvisional: true,
        },
      });
      const nextState = mapPermissionState(permission);
      setPermissionState(nextState);
      setLastError(null);
      return nextState === 'granted';
    } catch (error) {
      setLastError(error instanceof Error ? error.message : '通知授权失败');
      return false;
    }
  }

  const syncRemotePush = useCallback(
    async (allowPermissionPrompt: boolean) => {
      if (!isSupported) {
        setRemotePushState('unsupported');
        return false;
      }

      if (!token || !user) {
        setRemotePushState('idle');
        return false;
      }

      let granted = permissionState === 'granted';
      if (!granted && allowPermissionPrompt) {
        granted = await requestPermission();
      }
      if (!granted) {
        setRemotePushState('idle');
        return false;
      }

      if (!EXPO_PROJECT_ID) {
        setRemotePushState('error');
        setLastError('缺少 EAS projectId，当前无法注册远程推送。');
        return false;
      }

      setRemotePushState('syncing');

      try {
        const pushTokenResponse = await Notifications.getExpoPushTokenAsync({
          projectId: EXPO_PROJECT_ID,
        });
        const nextExpoPushToken = pushTokenResponse.data;
        const effectivePermissionState = granted ? 'granted' : permissionState;
        setExpoPushToken(nextExpoPushToken);

        const maybeConstants = Constants as { deviceName?: string };
        const deviceName =
          (typeof maybeConstants.deviceName === 'string' && maybeConstants.deviceName) ||
          `${Platform.OS.toUpperCase()} 设备`;

        const registration = await registerPushDevice(
          {
            expoPushToken: nextExpoPushToken,
            platform: Platform.OS,
            deviceName,
            appVersion: Constants.expoConfig?.version ?? '1.0.0',
            permissionState: effectivePermissionState,
          },
          token
        );
        setRemotePushState('ready');
        setLastDispatchResult(registration.takeoverDispatch);
        setLastError(
          registration.takeoverDispatch?.failedDevices
            ? `同步后自动补发部分失败，成功 ${registration.takeoverDispatch.sentDevices} 台，失败 ${registration.takeoverDispatch.failedDevices} 台。`
            : null
        );
        return true;
      } catch (error) {
        setRemotePushState('error');
        setLastError(error instanceof Error ? error.message : '远程推送注册失败');
        return false;
      }
    },
    [isSupported, permissionState, token, user]
  );

  const maybeRunTakeoverAutoCheck = useCallback(async (assumeReady = false) => {
    if (!token || !user || (!assumeReady && remotePushState !== 'ready')) {
      return;
    }

    try {
      const takeoverStatus = await getTakeoverPushStatus(token);
      const runKey = [
        takeoverStatus.fingerprint,
        takeoverStatus.activeDevices,
        takeoverStatus.pendingDevices,
        takeoverStatus.autoEnabled ? 'auto' : 'manual',
        takeoverStatus.autoCooldownSeconds,
      ].join('|');

      if (lastTakeoverAutoCheckRef.current === runKey) {
        return;
      }
      lastTakeoverAutoCheckRef.current = runKey;

      if (
        !takeoverStatus.autoEnabled ||
        !takeoverStatus.shouldSend ||
        takeoverStatus.autoCooldownSeconds > 0 ||
        takeoverStatus.activeDevices === 0
      ) {
        return;
      }

      const result = await runTakeoverPushAuto({}, token);
      setLastDispatchResult(result);
      setLastError(
        result.failedDevices > 0
          ? `自动下发部分失败，成功 ${result.sentDevices} 台，失败 ${result.failedDevices} 台。`
          : null
      );
    } catch (error) {
      setLastError(error instanceof Error ? error.message : '自动检查接管判断失败');
    }
  }, [remotePushState, token, user]);

  useEffect(() => {
    if (!isSupported || permissionState !== 'granted' || !token || !user) {
      return;
    }

    void syncRemotePush(false);
  }, [apiBaseUrl, isSupported, permissionState, syncRemotePush, token, user]);

  useEffect(() => {
    if (remotePushState !== 'ready' || !token || !user) {
      return;
    }

    void maybeRunTakeoverAutoCheck();
  }, [maybeRunTakeoverAutoCheck, remotePushState, token, user]);

  useEffect(() => {
    if (!isSupported) {
      return;
    }

    const subscription = AppState.addEventListener('change', (nextState) => {
      if (nextState !== 'active') {
        return;
      }
      if (!token || !user || permissionState !== 'granted') {
        return;
      }

      const now = Date.now();
      if (now - lastForegroundRefreshAtRef.current < FOREGROUND_SYNC_DEBOUNCE_MS) {
        return;
      }
      lastForegroundRefreshAtRef.current = now;

      void (async () => {
        const ready = await syncRemotePush(false);
        if (!ready) {
          return;
        }
        await maybeRunTakeoverAutoCheck(true);
      })();
    });

    return () => {
      subscription.remove();
    };
  }, [isSupported, maybeRunTakeoverAutoCheck, permissionState, syncRemotePush, token, user]);

  async function sendPreviewNotification() {
    const granted = permissionState === 'granted' ? true : await requestPermission();
    if (!granted) {
      setLastError('通知权限未开启');
      return;
    }

    await Notifications.scheduleNotificationAsync({
      content: {
        title: 'Alpha AI 提醒已开启',
        body: '后续关键风险和高优先级信号会以本地通知方式提示。',
        sound: true,
      },
      trigger: null,
    });
  }

  async function registerRemotePush() {
    return syncRemotePush(true);
  }

  async function sendRemotePreviewNotification() {
    const ready = remotePushState === 'ready' ? true : await syncRemotePush(true);
    if (!ready) {
      return;
    }

    try {
      const result = await sendPushTest(
        {
          title: 'Alpha AI 远程推送测试',
          body: '这条消息来自后端下发链路，用来验证 Expo Push 服务是否可达。',
          route: '/alerts',
        },
        token ?? undefined
      );
      setLastError(
        result.failedDevices > 0
          ? `远程推送部分失败，成功 ${result.sentDevices} 台，失败 ${result.failedDevices} 台。`
          : null
      );
      setLastDispatchResult(result);
    } catch (error) {
      setLastError(error instanceof Error ? error.message : '远程推送发送失败');
    }
  }

  async function sendRemoteTakeoverPreview() {
    if (!token) {
      return;
    }

    try {
      const result = await sendTakeoverPush({ dryRun: true }, token ?? undefined);
      setLastDispatchResult(result);
      setLastError(null);
    } catch (error) {
      setLastError(error instanceof Error ? error.message : '接管判断预演失败');
    }
  }

  async function sendRemoteTakeoverNotification() {
    const ready = remotePushState === 'ready' ? true : await syncRemotePush(true);
    if (!ready) {
      return;
    }

    try {
      const result = await sendTakeoverPush({}, token ?? undefined);
      setLastDispatchResult(result);
      setLastError(
        result.failedDevices > 0
          ? `接管判断推送部分失败，成功 ${result.sentDevices} 台，失败 ${result.failedDevices} 台。`
          : null
      );
    } catch (error) {
      setLastError(error instanceof Error ? error.message : '接管判断推送失败');
    }
  }

  async function sendRemoteTakeoverResend() {
    const ready = remotePushState === 'ready' ? true : await syncRemotePush(true);
    if (!ready) {
      return;
    }

    try {
      const result = await sendTakeoverPush({ force: true }, token ?? undefined);
      setLastDispatchResult(result);
      setLastError(
        result.failedDevices > 0
          ? `接管判断重发部分失败，成功 ${result.sentDevices} 台，失败 ${result.failedDevices} 台。`
          : null
      );
    } catch (error) {
      setLastError(error instanceof Error ? error.message : '接管判断重发失败');
    }
  }

  async function runRemoteTakeoverAuto() {
    const ready = remotePushState === 'ready' ? true : await syncRemotePush(true);
    if (!ready) {
      return;
    }

    try {
      const result = await runTakeoverPushAuto({}, token ?? undefined);
      setLastDispatchResult(result);
      setLastError(
        result.failedDevices > 0
          ? `自动下发部分失败，成功 ${result.sentDevices} 台，失败 ${result.failedDevices} 台。`
          : null
      );
    } catch (error) {
      setLastError(error instanceof Error ? error.message : '自动下发执行失败');
    }
  }

  async function pushRiskAlerts(alerts: RiskAlert[]) {
    if (!isSupported || permissionState !== 'granted') {
      return;
    }

    const nextAlerts = alerts.filter(
      (alert) =>
        !notifiedAlertIdsRef.current.has(alert.id) &&
        (alert.level === 'critical' || alert.level === 'warning' || alert.source === 'signal')
    );

    if (nextAlerts.length === 0) {
      return;
    }

    for (const alert of nextAlerts.slice(0, 3)) {
      await Notifications.scheduleNotificationAsync({
        identifier: `risk-${alert.id}`,
        content: {
          title: alert.level === 'critical' ? `紧急: ${alert.title}` : alert.title,
          body: alert.message,
          sound: true,
          data: {
            alertId: alert.id,
            route: alert.route,
            source: alert.source,
            sourceId: alert.sourceId,
          },
        },
        trigger: null,
      });

      notifiedAlertIdsRef.current.add(alert.id);
    }

    await setStoredValue(
      NOTIFIED_ALERT_IDS_KEY,
      JSON.stringify(Array.from(notifiedAlertIdsRef.current))
    );
  }

  async function pushTakeoverAction(actions: ActionBoardItem[]) {
    if (!isSupported || permissionState !== 'granted') {
      return;
    }

    const takeover = actions.find((item) => item.kind === 'takeover');
    if (!takeover) {
      return;
    }

    const fingerprint = [takeover.sourceId, takeover.title, takeover.summary].join('|');
    if (lastTakeoverActionRef.current === fingerprint) {
      return;
    }

    await Notifications.scheduleNotificationAsync({
      identifier: `takeover-${takeover.sourceId}`,
      content: {
        title: takeover.title,
        body: takeover.summary,
        sound: true,
        data: {
          route: takeover.route,
          source: takeover.source,
          sourceId: takeover.sourceId,
        },
      },
      trigger: null,
    });

    lastTakeoverActionRef.current = fingerprint;
    await setStoredValue(LAST_TAKEOVER_ACTION_KEY, fingerprint);
  }

  return (
    <NotificationContext.Provider
      value={{
        isSupported,
        isBooting,
        permissionState,
        remotePushState,
        expoPushToken,
        lastError,
        lastDispatchResult,
        requestPermission,
        sendPreviewNotification,
        registerRemotePush,
        sendRemotePreviewNotification,
        sendRemoteTakeoverNotification,
        sendRemoteTakeoverResend,
        sendRemoteTakeoverPreview,
        runRemoteTakeoverAuto,
        pushRiskAlerts,
        pushTakeoverAction,
      }}>
      {children}
    </NotificationContext.Provider>
  );
}

export function useNotifications() {
  const context = useContext(NotificationContext);

  if (!context) {
    throw new Error('useNotifications must be used within NotificationProvider');
  }

  return context;
}
