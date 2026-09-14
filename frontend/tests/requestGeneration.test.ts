import { describe, expect, it } from "vitest";

import { isCurrentRequest, nextRequestId } from "../src/lib/requestGeneration";

describe("request generation", () => {
  it("ignores stale request ids", () => {
    const ref = { current: 0 };
    const first = nextRequestId(ref);
    const second = nextRequestId(ref);
    expect(isCurrentRequest(ref, first)).toBe(false);
    expect(isCurrentRequest(ref, second)).toBe(true);
  });
});
