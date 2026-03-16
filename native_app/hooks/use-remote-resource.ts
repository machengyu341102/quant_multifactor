import { DependencyList, useCallback, useEffect, useRef, useState, useTransition } from 'react';

export function useRemoteResource<T>(loader: () => Promise<T>, deps: DependencyList = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [isPending, startTransition] = useTransition();
  const loaderRef = useRef(loader);

  loaderRef.current = loader;

  const refresh = useCallback(async () => {
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
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, isPending, refreshing, refresh };
}
