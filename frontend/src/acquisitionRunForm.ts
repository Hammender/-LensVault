import type {
  AcquisitionCategory,
  AcquisitionRun,
  AcquisitionScript,
  AcquisitionScriptParameter,
  AcquisitionSource
} from "./types";

export type AcquisitionRunFormParameters = Record<string, string | boolean>;

export type AcquisitionRunFormConfiguration = {
  categoryId: string;
  scriptKey: string;
  mode: "incremental" | "verify";
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
  return Object.fromEntries(script.parameters.map((parameter) => {
    const fallback = parameterDefault(parameter);
    if (!Object.prototype.hasOwnProperty.call(snapshot, parameter.key)) return [parameter.key, fallback];
    const value = snapshot[parameter.key];
    if (parameter.type === "boolean") return [parameter.key, booleanSnapshotValue(value, Boolean(fallback))];
    return [parameter.key, value == null ? fallback : String(value)];
  }));
}

export function getAcquisitionRunFormConfiguration(
  run: AcquisitionRun,
  categories: AcquisitionCategory[],
  sources: AcquisitionSource[],
  scripts: AcquisitionScript[]
): AcquisitionRunFormConfiguration | null {
  if (!run.script_key || (run.mode !== "incremental" && run.mode !== "verify")) return null;
  const category = categories.find((item) => item.id === run.category_id && item.enabled);
  if (!category) return null;
  const source = sources.find((item) => item.id === category.source_id && item.enabled);
  if (!source?.script_keys.includes(run.script_key)) return null;
  const script = scripts.find((item) => item.key === run.script_key);
  if (!script) return null;
  return {
    categoryId: String(category.id),
    scriptKey: script.key,
    mode: run.mode,
    parameters: restoreAcquisitionRunParameters(script, run.parameters)
  };
}
