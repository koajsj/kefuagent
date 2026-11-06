export async function requestIdentity(
  payload: unknown,
  previous?: { digest: string; key: string } | null,
) {
  const bytes = new TextEncoder().encode(JSON.stringify(payload));
  const digest = Array.from(
    new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
    (b) => b.toString(16).padStart(2, "0"),
  ).join("");
  return previous?.digest === digest
    ? previous
    : { digest, key: crypto.randomUUID() };
}
