import type { Href } from 'expo-router';

const DEFAULT_ROUTE = '/(tabs)/index' as Href;

function buildDynamicHref(
  pathname: '/industry/[id]' | '/signal/[id]' | '/position/[code]',
  key: 'id' | 'code',
  value: string,
  query: URLSearchParams
): Href {
  const params: Record<string, string> = { [key]: decodeURIComponent(value) };

  query.forEach((queryValue, queryKey) => {
    params[queryKey] = queryValue;
  });

  return { pathname, params } as Href;
}

export function resolveAppHref(route?: Href | string | null, fallback: Href = DEFAULT_ROUTE): Href {
  if (!route) {
    return fallback;
  }

  if (typeof route !== 'string') {
    return route;
  }

  const trimmed = route.trim();
  if (!trimmed.startsWith('/')) {
    return fallback;
  }

  const [pathname, queryString = ''] = trimmed.split('?', 2);
  const query = new URLSearchParams(queryString);

  const industryCapitalMatch = pathname.match(/^\/industry-capital\/([^/]+)$/);
  if (industryCapitalMatch) {
    return buildDynamicHref('/industry/[id]', 'id', industryCapitalMatch[1], query);
  }

  const signalMatch = pathname.match(/^\/signal\/([^/]+)$/);
  if (signalMatch) {
    return buildDynamicHref('/signal/[id]', 'id', signalMatch[1], query);
  }

  const positionMatch = pathname.match(/^\/position\/([^/]+)$/);
  if (positionMatch) {
    return buildDynamicHref('/position/[code]', 'code', positionMatch[1], query);
  }

  return trimmed as Href;
}
