import { PropsWithChildren, createContext, useContext, useMemo } from 'react';
import { Platform } from 'react-native';

import type { ActionBoardItem, PushDispatchResult, RiskAlert } from '@/types/trading';

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

const NotificationContext = createContext<NotificationContextValue | null>(null);

async function noopAsync() {}
async function noopBool() {
  return false;
}

export function NotificationProvider({ children }: PropsWithChildren) {
  const value = useMemo<NotificationContextValue>(
    () => ({
      isSupported: Platform.OS !== 'web',
      isBooting: false,
      permissionState: 'unsupported',
      remotePushState: 'unsupported',
      expoPushToken: null,
      lastError: null,
      lastDispatchResult: null,
      requestPermission: noopBool,
      sendPreviewNotification: noopAsync,
      registerRemotePush: noopBool,
      sendRemotePreviewNotification: noopAsync,
      sendRemoteTakeoverNotification: noopAsync,
      sendRemoteTakeoverResend: noopAsync,
      sendRemoteTakeoverPreview: noopAsync,
      runRemoteTakeoverAuto: noopAsync,
      pushRiskAlerts: noopAsync,
      pushTakeoverAction: noopAsync,
    }),
    []
  );

  return <NotificationContext.Provider value={value}>{children}</NotificationContext.Provider>;
}

export function useNotifications() {
  const context = useContext(NotificationContext);

  if (!context) {
    throw new Error('useNotifications must be used within NotificationProvider');
  }

  return context;
}
