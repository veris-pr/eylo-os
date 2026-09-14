import { useState, type FC } from "preact/compat";
import type { TWidgetInteraction, TWidgetResponseData } from "@eylo";
import { Button, Card, CardContent, CardHeader, CardTitle, Flex, cm } from "../index";
import type { TWidgetButtonGroupPayload } from "./types";
import styles from "./WidgetButtonGroup.module.css";

type WidgetButtonGroupProps = {
  payload: TWidgetButtonGroupPayload;
  onInteraction?: (interaction: TWidgetInteraction) => boolean;
  isReadOnly?: boolean;
  submission?: TWidgetResponseData | null;
};

const toButtonVariant = (variant?: string) => {
  if (variant === "primary") return "default" as const;
  if (variant === "secondary") return "secondary" as const;
  if (variant === "destructive") return "destructive" as const;
  if (variant === "ghost") return "ghost" as const;
  if (variant === "outline") return "outline" as const;
  if (variant === "link") return "link" as const;
  return "default" as const;
};

export const WidgetButtonGroup: FC<WidgetButtonGroupProps> = ({
  payload,
  onInteraction,
  isReadOnly = false,
  submission = null,
}) => {
  const { props } = payload;
  const [isSubmitted, setIsSubmitted] = useState(Boolean(submission));
  const effectiveReadOnly = isReadOnly || isSubmitted;
  const isVertical = props.layout === "vertical";
  const [selectedValue, setSelectedValue] = useState<string | null>(() =>
    typeof submission?.data.value === "string" ? submission.data.value : null
  );

  return (
    <Card border shadow="none">
      {props.question ? (
        <CardHeader>
          <CardTitle>{props.question}</CardTitle>
        </CardHeader>
      ) : null}
      <CardContent>
        <Flex direction={isVertical ? "column" : "row"} wrap="wrap" gap="sm">
          {props.buttons.map((button) => (
            <Button
              key={button.value}
              variant={toButtonVariant(button.variant)}
              size="lg"
              className={cm(
                isVertical && styles.verticalButton,
                selectedValue === button.value && styles.selectedButton
              )}
              aria-pressed={selectedValue === button.value}
              onClick={() => {
                const accepted = onInteraction?.({
                  component: "button_group",
                  action: "select",
                  data: { value: button.value, label: button.label },
                });
                if (accepted) {
                  setSelectedValue(button.value);
                  setIsSubmitted(true);
                }
              }}
              disabled={effectiveReadOnly}
            >
              {button.label}
            </Button>
          ))}
        </Flex>
      </CardContent>
    </Card>
  );
};
