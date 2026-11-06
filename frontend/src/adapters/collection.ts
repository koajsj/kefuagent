import type { Adapter, Row } from "../types";
export async function collection<T = Row>(
  request: Adapter["request"],
  path: string,
  cap = 500,
  signal?: AbortSignal,
): Promise<T[]> {
  const rows: T[] = [],
    separator = path.includes("?") ? "&" : "?";
  for (let offset = 0; offset < cap; ) {
    const limit = Math.min(100, cap - offset);
    const page = await request<T[]>(
      `${path}${separator}limit=${limit}&offset=${offset}`,
      { signal },
    );
    rows.push(...page);
    offset += page.length;
    if (page.length < limit) return rows;
  }
  if (
    (await request<T[]>(`${path}${separator}limit=1&offset=${cap}`, { signal }))
      .length
  )
    throw new Error(`条目超过 ${cap} 项，请使用搜索或分页。`);
  return rows;
}
