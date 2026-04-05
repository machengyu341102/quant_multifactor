import { useFocusEffect } from 'expo-router';
import { DependencyList, useCallback, useEffect, useRef, useState, useTransition } from 'react';

interface UseRemoteResourceOptions {
  refreshOnFocus?: boolean;
  focusThrottleMs?: number;
}

export function useRemoteResource<T>(
  loader: () => Promise<T>,
  deps: DependencyList = [],
  options: UseRemoteResourceOptions = {}
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [isPending, startTransition] = useTransition();
  const loaderRef = useRef(loader);
  const optionsRef = useRef(options);
  const lastRefreshStartedAtRef = useRef(0);

  loaderRef.current = loader;
  optionsRef.current = options;

  const refresh = useCallback(async (reason: 'manual' | 'deps' | 'focus' = 'manual') => {
    if (reason === 'focus' && !optionsRef.current.refreshOnFocus) {
      return;
    }
    const focusThrottleMs = optionsRef.current.focusThrottleMs ?? 15_000;
    const now = Date.now();
    if (reason === 'focus' && now - lastRefreshStartedAtRef.current < focusThrottleMs) {
      return;
    }
    lastRefreshStartedAtRef.current = now;
    setRefreshing(true);
    setError(null);

    try {
      const next = await loaderRef.current();
      startTransition(() => {
        setData(next);
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '请求失败');
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void refresh('deps');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useFocusEffect(
    useCallback(() => {
      if (!optionsRef.current.refreshOnFocus) {
        return undefined;
      }
      void refresh('focus');
      return undefined;
    }, [refresh])
  );

  return { data, error, isPending, refreshing, refresh };
}
