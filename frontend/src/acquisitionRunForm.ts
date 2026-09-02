import type {
  AcquisitionCategory,
  AcquisitionRun,
  AcquisitionScript,
  AcquisitionScriptParameter,
  AcquisitionSource
} from "./types";
import { toShanghaiDateTimeLocalValue, toShanghaiDateTimeOffset } from "./utils";

export type AcquisitionRunFormParameters = Record<string, string | boolean>;
export type AcquisitionRunMode = "incremental" | "full" | "verify";

export type AcquisitionRunFormConfiguration = {
  categoryId: string;
  scriptKey: string;
  mode: AcquisitionRunMode;
  parameters: AcquisitionRunFormParameters;
};

function parameterDefault(parameter: AcquisitionScriptParameter): string | boolean {
  if (parameter.type === "boolean") return Boolean(parameter.default);
  return parameter.default == null ? "" : String(parameter.default);
}

function booleanSnapshotValue(value: unknown, fallback: boolean): boolean {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (normalized === "true" || normalized === "1") return true;
    if (normalized === "false" || normalized === "0") return false;
  }
  return fallback;
}

export function defaultAcquisitionRunParameters(script: AcquisitionScript | undefined): AcquisitionRunFormParameters {
  return Object.fromEntries((script?.parameters ?? []).map((parameter) => [parameter.key, parameterDefault(parameter)]));
}

export function restoreAcquisitionRunParameters(
  script: AcquisitionScript,
  snapshot: Record<string, unknown>
): AcquisitionRunFormParameters {
  const normalizedSnapshot = script.key === "shfwzwz-raindrop-page"
    && Object.prototype.hasOwnProperty.call(snapshot, "max_pages")
    && !Object.prototype.hasOwnProperty.call(snapshot, "end_page")
    ? { ...snapshot, start_page: 1, end_page: snapshot.max_pages }
    : snapshot;
  return Object.fromEntries(script.parameters.map((parameter) => {
    const fallback = parameterDefault(parameter);
    if (!Object.prototype.hasOwnProperty.call(normalizedSnapshot, parameter.key)) return [parameter.key, fallback];
    const value = normalizedSnapshot[parameter.key];
    if (parameter.type === "boolean") return [parameter.key, booleanSnapshotValue(value, Boolean(fallback))];
    if (value == null) return [parameter.key, fallback];
    if (parameter.type === "datetime") return [parameter.key, toShanghaiDateTimeLocalValue(String(value))];
    return [parameter.key, String(value)];
  }));
}

export function serializeAcquisitionRunParameters(
  script: AcquisitionScript | undefined,
  parameters: AcquisitionRunFormParameters
): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const parameter of script?.parameters ?? []) {
    const value = parameters[parameter.key];
    if (value === "" && !parameter.required) continue;
    if (parameter.type === "integer" || parameter.type === "number") result[parameter.key] = Number(value);
    else if (parameter.type === "string_list") {
      result[parameter.key] = String(value).split(",").map((item) => item.trim()).filter(Boolean);
    } else if (parameter.type === "datetime") {
      result[parameter.key] = toShanghaiDateTimeOffset(String(value));
    } else {
      result[parameter.key] = value;
    }
  }
  const startPage = Number(result.start_page ?? 1);
  const endPage = result.end_page == null ? null : Number(result.end_page);
  if (endPage != null && endPage < startPage) throw new Error("结束页不能小于起始页");
  return result;
}

export function getAcquisitionRunFormConfiguration(
  run: AcquisitionRun,
  categories: AcquisitionCategory[],
  sources: AcquisitionSource[],
  scripts: AcquisitionScript[]
): AcquisitionRunFormConfiguration | null {
  if (!run.script_key) return null;
  const category = categories.find((item) => item.id === run.category_id && item.enabled);
  if (!category) return null;
  const source = sources.find((item) => item.id === category.source_id && item.enabled);
  if (!source?.script_keys.includes(run.script_key)) return null;
  const script = scripts.find((item) => item.key === run.script_key);
  if (!script) return null;
  const mode: AcquisitionRunMode | null = run.mode === "full" || run.mode === "verify"
    ? run.mode
    : run.mode === "incremental"
      ? run.parameters.force_full_scan === true ? "full" : "incremental"
      : null;
  if (!mode) return null;
  return {
    categoryId: String(category.id),
    scriptKey: script.key,
    mode,
    parameters: restoreAcquisitionRunParameters(script, run.parameters)
  };
}
