function formatSorIdentifier(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatSorDate(value: string | null | undefined): {
  label: string;
  title?: string;
} {
  if (value === null || value === undefined || value === "") {
    return { label: "Not recorded" };
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return { label: value };
  const absolute = new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
  const elapsedSeconds = Math.round((date.getTime() - Date.now()) / 1000);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  const units = [
    [31_536_000, "year"],
    [2_592_000, "month"],
    [86_400, "day"],
    [3_600, "hour"],
    [60, "minute"],
  ] as const;
  for (const [seconds, unit] of units) {
    if (Math.abs(elapsedSeconds) >= seconds) {
      return {
        label: formatter.format(Math.round(elapsedSeconds / seconds), unit),
        title: absolute,
      };
    }
  }
  return { label: "just now", title: absolute };
}

function formatSorValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  if (Array.isArray(value)) return value.map(formatSorValue).join(", ");
  try {
    return JSON.stringify(value);
  } catch {
    return "Unsupported value";
  }
}

function formatSorNumber(value: unknown): string {
  if (typeof value === "number") return String(value);
  if (typeof value !== "string") return formatSorValue(value);
  const normalized = value.trim();
  if (/^-?0+(?:\.0+)?(?:e[+-]?\d+)?$/i.test(normalized)) return "0";
  if (!/^-?\d+(?:\.\d+)?$/.test(normalized)) return normalized;
  if (!normalized.includes(".")) return normalized;
  return normalized.replace(/0+$/, "").replace(/\.$/, "");
}

export { formatSorDate, formatSorIdentifier, formatSorNumber, formatSorValue };
