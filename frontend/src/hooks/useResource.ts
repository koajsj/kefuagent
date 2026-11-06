import { useEffect, useRef, useState, type DependencyList } from "react";
export function useResource<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  deps: DependencyList,
) {
  const [data, setData] = useState<T>(),
    [error, setError] = useState<unknown>(),
    [loading, setLoading] = useState(true),
    [revision, setRevision] = useState(0);
  const load = useRef(loader);
  load.current = loader;
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(undefined);
    setData(undefined);
    load
      .current(controller.signal)
      .then(
        (value) => {
          if (!controller.signal.aborted) setData(value);
        },
        (error) => {
          if (!controller.signal.aborted && error?.name !== "StaleResponse")
            setError(error);
        },
      )
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [...deps, revision]);
  return {
    data,
    error,
    loading,
    reload: () => setRevision((value) => value + 1),
  };
}
