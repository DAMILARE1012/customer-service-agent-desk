import { useEffect, useRef } from 'react';

/** Keeps a scroll container pinned to the bottom whenever `dependency` changes. */
export function useAutoScroll(dependency) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  }, [dependency]);
  return ref;
}
