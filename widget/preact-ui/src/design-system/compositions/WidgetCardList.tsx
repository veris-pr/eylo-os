import type { FC } from "preact/compat";
import { useMemo, useState } from "preact/hooks";
import type { TWidgetInteraction, TWidgetResponseData } from "@eylo";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
  Flex,
  Stack,
  Text,
  cm,
} from "../index";
import styles from "./WidgetCardList.module.css";
import type { TWidgetCardListPayload } from "./types";

type WidgetCardListProps = {
  payload: TWidgetCardListPayload;
  onInteraction?: (interaction: TWidgetInteraction) => boolean;
  isReadOnly?: boolean;
  submission?: TWidgetResponseData | null;
};

export const WidgetCardList: FC<WidgetCardListProps> = ({
  payload,
  onInteraction,
  isReadOnly = false,
  submission = null,
}) => {
  const { props } = payload;
  const [selectedIds, setSelectedIds] = useState<string[]>(() =>
    Array.isArray(submission?.data.selectedIds)
      ? submission.data.selectedIds.filter((value): value is string => typeof value === "string")
      : []
  );
  const [isSubmitted, setIsSubmitted] = useState(Boolean(submission));

  const effectiveReadOnly = isReadOnly || isSubmitted;
  const selectionMode = props.selectionMode || "single";

  const selectedCount = useMemo(() => selectedIds.length, [selectedIds]);

  const toggleSelection = (cardId: string): void => {
    if (effectiveReadOnly) {
      return;
    }

    if (selectionMode === "single") {
      setSelectedIds([cardId]);
      return;
    }

    setSelectedIds((previous) =>
      previous.includes(cardId)
        ? previous.filter((currentId) => currentId !== cardId)
        : [...previous, cardId]
    );
  };

  const handleSubmit = (): void => {
    if (selectedIds.length === 0) {
      return;
    }

    const accepted = onInteraction?.({
      component: "card_list",
      action: "submit",
      data: { selectedIds },
    });
    if (accepted) {
      setIsSubmitted(true);
    }
  };

  return (
    <Card border shadow="none">
      {props.title || props.description ? (
        <CardHeader>
          {props.title ? <CardTitle>{props.title}</CardTitle> : null}
          {props.description ? <CardDescription>{props.description}</CardDescription> : null}
        </CardHeader>
      ) : null}
      <CardContent>
        <div className={styles.optionList}>
          {props.cards.map((card) => {
            const isSelected = selectedIds.includes(card.id);
            const visibleFeatures = card.features?.filter(
              (feature, index, features) =>
                feature !== card.description && features.indexOf(feature) === index
            );

            return (
              <button
                key={card.id}
                type="button"
                className={styles.cardButton}
                onClick={() => toggleSelection(card.id)}
                disabled={effectiveReadOnly}
                aria-pressed={isSelected}
              >
                <div className={cm(styles.cardOption, isSelected && styles.cardSelected)}>
                  <Stack spacing="sm">
                    {card.image ? (
                      <img src={card.image} alt={card.title} className={styles.cardMedia} />
                    ) : null}
                    <Flex justify="between" align="center" gap="sm">
                      <CardTitle>{card.title}</CardTitle>
                      {card.badge ? <Badge>{card.badge}</Badge> : null}
                    </Flex>
                    {card.description ? <Text variant="muted">{card.description}</Text> : null}
                    {card.price ? <Text semibold>{card.price}</Text> : null}
                    {visibleFeatures?.length ? (
                      <ul className={styles.featureList}>
                        {visibleFeatures.map((feature) => (
                          <li key={feature}>
                            <Text size="small">{feature}</Text>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </Stack>
                </div>
              </button>
            );
          })}
        </div>
      </CardContent>
      {!effectiveReadOnly ? (
        <CardFooter>
          <Button size="lg" width="full" onClick={handleSubmit} disabled={selectedCount === 0}>
            {props.submitLabel || "Select"}
          </Button>
        </CardFooter>
      ) : null}
    </Card>
  );
};
