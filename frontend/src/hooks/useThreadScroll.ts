import { useLayoutEffect, useRef } from "react";

export function useThreadScroll(messages: unknown[], offset: number, loading: boolean) {
  const thread = useRef<HTMLDivElement>(null);
  const nearBottom = useRef(true);
  const requested = useRef(false);
  const onScroll = () => {
    const el = thread.current;
    if (el) nearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  };
  const jumpToLatest = () => {
    requested.current = true;
    if (offset === 0 && thread.current) {
      thread.current.scrollTop = thread.current.scrollHeight;
      nearBottom.current = true;
      requested.current = false;
    }
  };
  useLayoutEffect(() => {
    const el = thread.current;
    if (!el || loading || offset !== 0 || (!nearBottom.current && !requested.current)) return;
    el.scrollTop = el.scrollHeight;
    nearBottom.current = true;
    requested.current = false;
  }, [messages, offset, loading]);
  return { thread, onScroll, jumpToLatest, nearBottom };
}
