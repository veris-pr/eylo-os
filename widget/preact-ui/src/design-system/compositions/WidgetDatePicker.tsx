import type { FC } from "preact/compat";
import { useState } from "preact/hooks";
import type { TWidgetInteraction, TWidgetResponseData } from "@eylo";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
  Field,
  Input,
} from "../index";
import { nativeDateConstraint, validateDatePickerValue } from "./validation";
import type { TWidgetDatePickerPayload } from "./types";
import styles from "./WidgetDatePicker.module.css";

type WidgetDatePickerProps = {
  payload: TWidgetDatePickerPayload;
  instanceId?: string;
  onInteraction?: (interaction: TWidgetInteraction) => boolean;
  isReadOnly?: boolean;
  submission?: TWidgetResponseData | null;
};

const INPUT_TYPE_MAP: Record<string, string> = {
  date: "date",
  time: "time",
  datetime: "datetime-local",
};

const formatDisplayValue = (mode: string, raw: string): string => {
  if (!raw) return "";
  try {
    if (mode === "time") {
      const [h, m] = raw.split(":");
      const hour = Number(h);
      const ampm = hour >= 12 ? "PM" : "AM";
      const h12 = hour === 0 ? 12 : hour > 12 ? hour - 12 : hour;
      return `${h12}:${m} ${ampm}`;
    }
    if (mode === "date") {
      const d = new Date(raw + "T00:00:00");
      return d.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" });
    }
    if (mode === "datetime") {
      const d = new Date(raw);
      return d.toLocaleString("en-US", {
        year: "numeric",
        month: "long",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
    }
  } catch {
    /* fall through */
  }
  return raw;
};

export const WidgetDatePicker: FC<WidgetDatePickerProps> = ({
  payload,
  instanceId = "widget",
  onInteraction,
  isReadOnly = false,
  submission = null,
}) => {
  const { props } = payload;
  const mode = props.mode || "date";
  const inputType = INPUT_TYPE_MAP[mode] || "date";
  const controlId = `${instanceId}-${props.name}`;
  const descriptionId = props.description ? `${controlId}-description` : undefined;
  const nativeMode = mode === "datetime" ? "datetime" : "date";

  const submittedValue =
    typeof submission?.data[props.name] === "string" ? (submission.data[props.name] as string) : "";

  const [value, setValue] = useState(submittedValue || props.defaultValue || "");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitted, setIsSubmitted] = useState(Boolean(submission));
  const errorId = error ? `${controlId}-error` : undefined;

  const effectiveReadOnly = isReadOnly || isSubmitted;

  const handleSubmit = (): void => {
    const nextError = validateDatePickerValue(props, value);
    setError(nextError);
    if (nextError) return;

    const accepted = onInteraction?.({
      component: "date_picker",
      action: "submit",
      data: { [props.name]: value },
    });
    if (accepted) {
      setIsSubmitted(true);
    }
  };

  return (
    <Card border shadow="none">
      <CardHeader>
        <CardTitle id={`${controlId}-label`}>
          {props.label}
          {props.required ? <span aria-hidden="true"> *</span> : null}
        </CardTitle>
        {props.description ? (
          <CardDescription id={descriptionId}>{props.description}</CardDescription>
        ) : null}
      </CardHeader>
      <CardContent>
        {effectiveReadOnly && value ? (
          <div className={styles.selectedDisplay}>{formatDisplayValue(mode, value)}</div>
        ) : (
          <Field error={error || undefined} errorId={errorId}>
            <Input
              id={controlId}
              name={props.name}
              type={inputType}
              value={value}
              min={
                mode === "time"
                  ? undefined
                  : nativeDateConstraint(props.validation?.minDate, nativeMode, "min")
              }
              max={
                mode === "time"
                  ? undefined
                  : nativeDateConstraint(props.validation?.maxDate, nativeMode, "max")
              }
              required={props.required}
              aria-labelledby={`${controlId}-label`}
              aria-describedby={[descriptionId, errorId].filter(Boolean).join(" ") || undefined}
              error={Boolean(error)}
              disabled={effectiveReadOnly}
              onInput={(e) => {
                setValue((e.currentTarget as HTMLInputElement).value);
                if (error) {
                  setError(null);
                }
              }}
            />
          </Field>
        )}
      </CardContent>
      {!effectiveReadOnly ? (
        <CardFooter>
          <Button size="lg" width="full" onClick={handleSubmit} disabled={!value}>
            {props.submitLabel || "Select"}
          </Button>
        </CardFooter>
      ) : null}
    </Card>
  );
};
