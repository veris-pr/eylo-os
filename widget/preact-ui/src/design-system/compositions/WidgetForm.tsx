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
  Checkbox,
  Field,
  Input,
  RadioGroup,
  RadioGroupItem,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Stack,
  Textarea,
} from "../index";
import { nativeDateConstraint, validateFieldValue, validateFormValues } from "./validation";
import type { TWidgetFormField, TWidgetFormPayload } from "./types";

type WidgetFormProps = {
  payload: TWidgetFormPayload;
  instanceId?: string;
  onInteraction?: (interaction: TWidgetInteraction) => boolean;
  isReadOnly?: boolean;
  submission?: TWidgetResponseData | null;
};

const getInputType = (field: TWidgetFormField): string => {
  if (field.type === "phone") return "tel";
  if (field.type === "datetime") return "datetime-local";
  return field.type;
};

const buildInitialValues = (fields: TWidgetFormField[]): Record<string, unknown> => {
  return fields.reduce<Record<string, unknown>>((accumulator, field) => {
    if (field.defaultValue !== undefined) {
      accumulator[field.name] = field.defaultValue;
      return accumulator;
    }

    accumulator[field.name] = field.type === "checkbox" ? false : "";
    return accumulator;
  }, {});
};

export const WidgetForm: FC<WidgetFormProps> = ({
  payload,
  instanceId = "widget",
  onInteraction,
  isReadOnly = false,
  submission = null,
}) => {
  const { props } = payload;
  const [values, setValues] = useState<Record<string, unknown>>(() => {
    const initialValues = buildInitialValues(props.fields);
    return submission?.data ? { ...initialValues, ...submission.data } : initialValues;
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isSubmitted, setIsSubmitted] = useState(Boolean(submission));

  const effectiveReadOnly = isReadOnly || isSubmitted;

  const updateValue = (field: TWidgetFormField, nextValue: unknown): void => {
    setValues((previous) => ({
      ...previous,
      [field.name]: nextValue,
    }));

    setErrors((previous) => {
      const nextErrors = { ...previous };
      const nextError = validateFieldValue(field, nextValue);

      if (nextError) {
        nextErrors[field.name] = nextError;
      } else {
        delete nextErrors[field.name];
      }

      return nextErrors;
    });
  };

  const handleSubmit = (): void => {
    const nextErrors = validateFormValues(props, values);
    setErrors(nextErrors);

    if (Object.keys(nextErrors).length > 0) {
      const firstInvalidField = props.fields.find((field) => nextErrors[field.name]);
      if (firstInvalidField) {
        requestAnimationFrame(() => {
          document.getElementById(`${instanceId}-${firstInvalidField.name}`)?.focus();
        });
      }
      return;
    }

    const accepted = onInteraction?.({
      component: "form",
      action: "submit",
      data: values,
    });
    if (accepted) {
      setIsSubmitted(true);
    }
  };

  const handleCancel = (): void => {
    onInteraction?.({
      component: "form",
      action: "cancel",
      data: values,
    });
  };

  const renderField = (field: TWidgetFormField) => {
    const fieldValue = values[field.name];
    const fieldError = errors[field.name];
    const controlId = `${instanceId}-${field.name}`;
    const errorId = fieldError ? `${controlId}-error` : undefined;

    if (field.type === "textarea") {
      return (
        <Field
          key={field.name}
          label={field.label}
          htmlFor={controlId}
          required={field.required}
          error={fieldError}
          errorId={errorId}
        >
          <Textarea
            id={controlId}
            name={field.name}
            value={String(fieldValue ?? "")}
            placeholder={field.placeholder}
            error={Boolean(fieldError)}
            aria-describedby={errorId}
            disabled={effectiveReadOnly}
            onInput={(event) =>
              updateValue(field, (event.currentTarget as HTMLTextAreaElement).value)
            }
          />
        </Field>
      );
    }

    if (field.type === "select") {
      return (
        <Field
          key={field.name}
          label={field.label}
          htmlFor={controlId}
          required={field.required}
          error={fieldError}
          errorId={errorId}
        >
          <Select
            value={typeof fieldValue === "string" ? fieldValue : undefined}
            onValueChange={(nextValue) => updateValue(field, nextValue)}
            disabled={effectiveReadOnly}
          >
            <SelectTrigger
              id={controlId}
              error={Boolean(fieldError)}
              aria-invalid={Boolean(fieldError) || undefined}
              aria-describedby={errorId}
              placeholder={field.placeholder || "Select..."}
            >
              <SelectValue placeholder={field.placeholder || "Select..."} />
            </SelectTrigger>
            <SelectContent>
              {field.options?.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      );
    }

    if (field.type === "radio") {
      const labelId = `${controlId}-label`;
      return (
        <Field
          key={field.name}
          label={field.label}
          labelId={labelId}
          required={field.required}
          error={fieldError}
          errorId={errorId}
        >
          <RadioGroup
            name={controlId}
            value={typeof fieldValue === "string" ? fieldValue : undefined}
            onValueChange={(nextValue) => updateValue(field, nextValue)}
            disabled={effectiveReadOnly}
            aria-labelledby={labelId}
            aria-describedby={errorId}
            aria-invalid={Boolean(fieldError) || undefined}
          >
            {field.options?.map((option) => (
              <RadioGroupItem
                key={option.value}
                value={option.value}
                label={option.label}
                description={option.description}
              />
            ))}
          </RadioGroup>
        </Field>
      );
    }

    if (field.type === "checkbox") {
      const labelId = `${controlId}-label`;
      return (
        <Field
          key={field.name}
          label={field.label}
          labelId={labelId}
          required={field.required}
          error={fieldError}
          errorId={errorId}
        >
          <Checkbox
            id={controlId}
            checked={Boolean(fieldValue)}
            disabled={effectiveReadOnly}
            onChange={(checked) => updateValue(field, checked)}
            label={field.placeholder || "Enable"}
            aria-labelledby={labelId}
            aria-describedby={errorId}
            aria-invalid={Boolean(fieldError) || undefined}
          />
        </Field>
      );
    }

    return (
      <Field
        key={field.name}
        label={field.label}
        htmlFor={controlId}
        required={field.required}
        error={fieldError}
        errorId={errorId}
      >
        <Input
          id={controlId}
          name={field.name}
          type={getInputType(field)}
          value={fieldValue === undefined ? "" : String(fieldValue)}
          min={
            field.type === "date" || field.type === "datetime"
              ? nativeDateConstraint(field.validation?.minDate, field.type, "min")
              : field.validation?.min
          }
          max={
            field.type === "date" || field.type === "datetime"
              ? nativeDateConstraint(field.validation?.maxDate, field.type, "max")
              : field.validation?.max
          }
          placeholder={field.placeholder}
          error={Boolean(fieldError)}
          aria-describedby={errorId}
          disabled={effectiveReadOnly}
          onInput={(event) => {
            const nextValue = (event.currentTarget as HTMLInputElement).value;
            updateValue(
              field,
              field.type === "number" && nextValue ? Number(nextValue) : nextValue
            );
          }}
        />
      </Field>
    );
  };

  return (
    <Card border shadow="none">
      <form
        onSubmit={(e: Event) => {
          e.preventDefault();
          handleSubmit();
        }}
      >
        <CardHeader>
          <CardTitle>{props.title}</CardTitle>
          {props.description ? <CardDescription>{props.description}</CardDescription> : null}
        </CardHeader>
        <CardContent>
          <Stack spacing="md">{props.fields.map(renderField)}</Stack>
        </CardContent>
        {!effectiveReadOnly ? (
          <CardFooter>
            <Stack spacing="sm">
              <Button type="submit" size="lg" width="full">
                {props.submitLabel || "Submit"}
              </Button>
              {props.cancelLabel ? (
                <Button size="lg" width="full" variant="outline" onClick={handleCancel}>
                  {props.cancelLabel}
                </Button>
              ) : null}
            </Stack>
          </CardFooter>
        ) : null}
      </form>
    </Card>
  );
};
