import type { FC } from "preact/compat";
import type {
  TCompoundWidgetPayload,
  TWidgetPayloadEnvelope,
  TWidgetResponseData,
} from "@eylo";
import { isCompoundWidgetPayload } from "@eylo";
import { Stack, Text } from "../../design-system";
import type {
  TWidgetButtonGroupProps,
  TWidgetCardListProps,
  TWidgetDatePickerProps,
  TWidgetFormProps,
} from "../../design-system/compositions/types";
import styles from "./WidgetResponseSummary.module.css";

type WidgetResponseSummaryProps = {
  response: TWidgetResponseData;
  sourcePayload?: TWidgetPayloadEnvelope | TCompoundWidgetPayload | null;
};

type SummaryEntry = {
  label: string;
  value: unknown;
};

/** Humanize a field key: "first_name" → "First name", "agreeTerms" → "Agree terms" */
const formatKey = (key: string): string => {
  const spaced = key
    .replace(/([a-z])([A-Z])/g, "$1 $2") // camelCase
    .replace(/[_-]+/g, " "); // snake_case / kebab-case
  return spaced.charAt(0).toUpperCase() + spaced.slice(1).toLowerCase();
};

const formatValue = (value: unknown): string => {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
};

const findSourcePayload = (
  payload: WidgetResponseSummaryProps["sourcePayload"],
  component: string
): TWidgetPayloadEnvelope | null => {
  if (!payload) {
    return null;
  }

  if (!isCompoundWidgetPayload(payload)) {
    return payload.component === component ? payload : null;
  }

  const node = payload.components.find((candidate) => candidate.component === component);
  return node
    ? ({ component: node.component, props: node.props } as TWidgetPayloadEnvelope)
    : null;
};

const formEntries = (
  data: Record<string, unknown>,
  props: TWidgetFormProps
): SummaryEntry[] => {
  const knownNames = new Set(props.fields.map((field) => field.name));
  const fields = props.fields
    .filter((field) => {
      const value = data[field.name];
      return (
        Object.prototype.hasOwnProperty.call(data, field.name) &&
        value !== "" &&
        value !== null &&
        value !== undefined &&
        (!Array.isArray(value) || value.length > 0)
      );
    })
    .map((field) => {
      const value = data[field.name];
      const optionLabel =
        typeof value === "string"
          ? field.options?.find((option) => option.value === value)?.label
          : undefined;
      return { label: field.label, value: optionLabel ?? value };
    });
  const extras = Object.entries(data)
    .filter(([name]) => !knownNames.has(name))
    .map(([name, value]) => ({ label: formatKey(name), value }));
  return [...fields, ...extras];
};

const resolveEntries = (
  response: TWidgetResponseData,
  sourcePayload: WidgetResponseSummaryProps["sourcePayload"]
): SummaryEntry[] => {
  const data = response.data ?? {};
  const source = findSourcePayload(sourcePayload, response.component);

  if (source?.component === "form") {
    return formEntries(data, source.props as TWidgetFormProps);
  }

  if (source?.component === "button_group") {
    const props = source.props as TWidgetButtonGroupProps;
    const value = typeof data.value === "string" ? data.value : null;
    const label =
      typeof data.label === "string"
        ? data.label
        : props.buttons.find((button) => button.value === value)?.label;
    return label ? [{ label: "Selection", value: label }] : [];
  }

  if (source?.component === "card_list") {
    const props = source.props as TWidgetCardListProps;
    const selectedIds = Array.isArray(data.selectedIds)
      ? data.selectedIds.filter((value): value is string => typeof value === "string")
      : [];
    const titlesById = new Map(props.cards.map((card) => [card.id, card.title]));
    return selectedIds.length > 0
      ? [
          {
            label: props.selectionMode === "multiple" ? "Selections" : "Selection",
            value: selectedIds.map((id) => titlesById.get(id) ?? id),
          },
        ]
      : [];
  }

  if (source?.component === "date_picker") {
    const props = source.props as TWidgetDatePickerProps;
    return Object.prototype.hasOwnProperty.call(data, props.name)
      ? [{ label: props.label, value: data[props.name] }]
      : [];
  }

  return Object.entries(data).map(([key, value]) => ({ label: formatKey(key), value }));
};

const submissionLabel = (component: string): string => {
  if (component === "form") return "Form submitted";
  if (component === "button_group") return "Choice submitted";
  if (component === "card_list") return "Selection submitted";
  if (component === "date_picker") return "Date selected";
  return `${formatKey(component)} submitted`;
};

export const WidgetResponseSummary: FC<WidgetResponseSummaryProps> = ({
  response,
  sourcePayload,
}) => {
  const entries = resolveEntries(response, sourcePayload);
  const hasData = entries.length > 0;

  return (
    <div className={styles.container}>
      <Text as="span" size="xs" variant="muted" semibold className={styles.header}>
        ✓ {submissionLabel(response.component)}
      </Text>
      {hasData && (
        <Stack spacing="xs">
          {entries.map(({ label, value }) => (
            <div key={label} className={styles.entry}>
              <Text as="span" size="xs" variant="muted">
                {label}
              </Text>
              <Text as="span" size="xs" semibold>
                {formatValue(value)}
              </Text>
            </div>
          ))}
        </Stack>
      )}
    </div>
  );
};
