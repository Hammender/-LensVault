export function nextRequestId(ref: { current: number }): number {
  ref.current += 1;
  return ref.current;
}

export function isCurrentRequest(ref: { current: number }, id: number): boolean {
  return ref.current === id;
}
