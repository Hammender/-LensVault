import { describe, expect, it } from "vitest";

import { isTerminalTask, isTerminalTaskStatus } from "../src/lib/taskStatus";
import type { Task } from "../src/types";

function task(status: string): Task {
  return {
    id: "1",
    kind: "person_import",
    status,
    message: null,
    progress: 1,
    created_at: "",
    updated_at: ""
  };
}

describe("task status", () => {
  it("treats completed, failed and canceled as terminal", () => {
    expect(isTerminalTaskStatus("pending")).toBe(false);
    expect(isTerminalTaskStatus("running")).toBe(false);
    expect(isTerminalTask(task("completed"))).toBe(true);
    expect(isTerminalTask(task("failed"))).toBe(true);
    expect(isTerminalTask(task("canceled"))).toBe(true);
    expect(isTerminalTask(null)).toBe(false);
  });
});
