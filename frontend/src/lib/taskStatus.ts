import type { Task } from "../types";

export function isTerminalTaskStatus(status: string): boolean {
  return status === "completed" || status === "failed" || status === "canceled";
}

export function isTerminalTask(task: Task | null | undefined): boolean {
  return Boolean(task && isTerminalTaskStatus(task.status));
}
