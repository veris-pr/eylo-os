import { Pencil, X } from "lucide-react";
import { observer } from "mobx-react-lite";

import { useRootStore } from "@/app/use-root-store";
import {
  DetailDisclosure,
  DetailRow,
  DetailSection,
  TechnicalDetails,
} from "@/components/details";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Drawer,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
} from "@/components/ui/drawer";
import { Skeleton } from "@/components/ui/skeleton";
import {
  formatContactDate,
  formatContactLifecycle,
} from "@/features/contacts/contact-formatters";

const ContactDetailsDrawer = observer(function ContactDetailsDrawer({
  contactId,
  onClose,
  onEdit,
}: {
  contactId: string | undefined;
  onClose: () => void;
  onEdit: (id: string) => void;
}) {
  const { contacts } = useRootStore();
  const contact = contacts.selectedContact;
  return (
    <Drawer
      open={contactId !== undefined}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      swipeDirection="right"
    >
      <DrawerContent className="[--drawer-content-width:min(100%,34rem)]">
        <DrawerHeader className="border-b p-5 pr-14 pb-5 text-left">
          <DrawerTitle className="[overflow-wrap:anywhere]">
            {contact?.name?.trim() ||
              contact?.primaryEmail ||
              "Contact details"}
          </DrawerTitle>
          <DrawerDescription>
            Saved identity, contact methods, and lifecycle.
          </DrawerDescription>
        </DrawerHeader>
        <Button
          className="absolute top-4 right-4 z-20"
          variant="ghost"
          size="icon"
          aria-label="Close contact details"
          onClick={onClose}
        >
          <X aria-hidden="true" />
        </Button>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {contacts.isSelectedLoading && contact === null ? (
            <div className="space-y-4">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-32 w-full" />
              <Skeleton className="h-32 w-full" />
            </div>
          ) : contacts.selectedErrorMessage !== null ? (
            <div
              className="border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
              role="alert"
            >
              {contacts.selectedErrorMessage}
            </div>
          ) : contact !== null ? (
            <div className="space-y-8">
              <DetailSection title="Identity">
                <DetailRow label="Name">
                  {contact.name ?? "Not provided"}
                </DetailRow>
                <DetailRow label="Lifecycle">
                  <Badge variant="outline">
                    {formatContactLifecycle(contact.lifecycle)}
                  </Badge>
                </DetailRow>
              </DetailSection>
              <DetailSection title="Contact methods">
                <DetailRow label="Email">
                  <span className="break-all">
                    {contact.primaryEmail ?? "Not provided"}
                  </span>
                </DetailRow>
                <DetailRow label="Phone">
                  <span className="break-all">
                    {contact.primaryPhone ?? "Not provided"}
                  </span>
                </DetailRow>
              </DetailSection>
              <DetailSection title="Preferences">
                {Object.entries(contact.preferences ?? {}).length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No preferences saved.
                  </p>
                ) : (
                  Object.entries(contact.preferences ?? {}).map(
                    ([key, value]) => (
                      <DetailRow key={key} label={key}>
                        <span className="break-words">{value}</span>
                      </DetailRow>
                    ),
                  )
                )}
              </DetailSection>
              <DetailDisclosure summary="Activity">
                <DetailRow label="Created">
                  <DateValue value={contact.createdAt} />
                </DetailRow>
                <DetailRow label="Updated">
                  <DateValue value={contact.updatedAt} />
                </DetailRow>
                {contact.deletionRequestedAt ? (
                  <DetailRow label="Deletion requested">
                    <DateValue value={contact.deletionRequestedAt} />
                  </DetailRow>
                ) : null}
              </DetailDisclosure>
              <TechnicalDetails>
                <DetailRow label="Contact ID">
                  <code className="break-all text-xs">{contact.id}</code>
                </DetailRow>
                <DetailRow label="External ID">
                  <code className="break-all text-xs">
                    {contact.externalId ?? "Not provided"}
                  </code>
                </DetailRow>
              </TechnicalDetails>
            </div>
          ) : null}
        </div>
        {contact !== null && contact.lifecycle === "active" ? (
          <DrawerFooter className="border-t p-4">
            <Button onClick={() => onEdit(contact.id)}>
              <Pencil aria-hidden="true" />
              Edit contact
            </Button>
          </DrawerFooter>
        ) : null}
      </DrawerContent>
    </Drawer>
  );
});

function DateValue({ value }: { value: string | null | undefined }) {
  const formatted = formatContactDate(value);
  return formatted.exact === null ? (
    formatted.label
  ) : (
    <time dateTime={formatted.exact}>{formatted.label}</time>
  );
}

export { ContactDetailsDrawer };
