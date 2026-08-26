import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface DetailSectionProps {
  children: ReactNode;
  description?: string;
  title: string;
}

function DetailSection({
  children,
  description,
  title,
}: DetailSectionProps) {
  return (
    <section className="min-w-0 space-y-3">
      <div className="space-y-1">
        <h2 className="text-sm font-semibold">{title}</h2>
        {description === undefined ? null : (
          <p className="text-sm leading-6 text-muted-foreground">
            {description}
          </p>
        )}
      </div>
      {children}
    </section>
  );
}

interface DetailRowProps {
  children: ReactNode;
  className?: string;
  label: string;
}

function DetailRow({ children, className, label }: DetailRowProps) {
  return (
    <div
      className={cn(
        "grid min-w-0 gap-1 border-b py-2.5 last:border-b-0 sm:grid-cols-[10rem_minmax(0,1fr)] sm:gap-4",
        className,
      )}
    >
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <div className="min-w-0 break-words text-sm">{children}</div>
    </div>
  );
}

interface DetailDisclosureProps {
  children: ReactNode;
  className?: string;
  summary: string;
}

function DetailDisclosure({
  children,
  className,
  summary,
}: DetailDisclosureProps) {
  return (
    <details className={cn("group min-w-0", className)}>
      <summary className="flex min-h-9 cursor-pointer list-none items-center gap-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
        <ChevronRight
          aria-hidden="true"
          className="size-4 shrink-0 transition-transform group-open:rotate-90"
        />
        {summary}
      </summary>
      <div className="mt-3 min-w-0">{children}</div>
    </details>
  );
}

type TechnicalDetailsProps = Omit<DetailDisclosureProps, "summary"> & {
  summary?: string;
};

function TechnicalDetails({
  children,
  className,
  summary = "Technical details",
}: TechnicalDetailsProps) {
  return (
    <DetailDisclosure className={className} summary={summary}>
      {children}
    </DetailDisclosure>
  );
}

export { DetailDisclosure, DetailRow, DetailSection, TechnicalDetails };
