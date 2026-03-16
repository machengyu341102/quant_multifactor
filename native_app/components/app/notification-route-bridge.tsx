import { useEffect, useRef } from 'react';
import * as Notifications from 'expo-notifications';
import { useRouter } from 'expo-router';

import { resolveAppHref } from '@/lib/app-routes';

function extractRoute(response: Notifications.NotificationResponse | null): string | null {
  const route = response?.notification.request.content.data?.route;
  if (typeof route !== 'string' || !route.startsWith('/')) {
    return null;
  }

  return route;
}

export function NotificationRouteBridge() {
  const router = useRouter();
  const handledNotificationIdRef = useRef<string | null>(null);

  useEffect(() => {
    async function consumeLastNotificationResponse() {
      const response = await Notifications.getLastNotificationResponseAsync();
      const notificationId = response?.notification.request.identifier ?? null;
      const route = extractRoute(response);

      if (!notificationId || !route || handledNotificationIdRef.current === notificationId) {
        return;
      }

      handledNotificationIdRef.current = notificationId;
      router.push(resolveAppHref(route));
    }

    void consumeLastNotificationResponse();

    const subscription = Notifications.addNotificationResponseReceivedListener((response) => {
      const notificationId = response.notification.request.identifier;
      const route = extractRoute(response);

      if (!route || handledNotificationIdRef.current === notificationId) {
        return;
      }

      handledNotificationIdRef.current = notificationId;
      router.push(resolveAppHref(route));
    });

    return () => {
      subscription.remove();
    };
  }, [router]);

  return null;
}
