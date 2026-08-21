# Configure a System of Record

Use this procedure to connect an available external source, select what Eylo
may synchronize, and grant the resulting source to an Agent.

Current executable adapters are HubSpot, Salesforce, Jira Cloud, Linear,
GitHub Issues, Zendesk, Intercom, Freshdesk, Confluence Cloud, and Notion. Their
live acceptance runs are still pending. Planned vendors cannot be configured
yet.

## Before you start

You need:

- an organization member session;
- permission to create an OAuth application for an OAuth vendor, a Freshdesk
  site URL and account API key, or a Notion internal integration token;
- the source objects and access level the organization intends to expose;
- an Agent draft if the source will be used by an Agent.

### Jira OAuth scope families

Jira uses three separate scope groups. Do not treat them as one interchangeable
list:

- **OAuth lifecycle scope:** `offline_access` is not a Jira API scope. It asks
  Atlassian for a refresh token so Eylo can keep the connection active.
- **Classic Jira Cloud platform scopes:** `read:jira-work` and
  `read:jira-user`; add `write:jira-work` for read/write sources. Atlassian
  recommends classic scopes where they cover the operation.
- **Granular Jira Software scopes:** selecting Sprints additionally requires
  `read:board-scope:jira-software`, `read:project:jira`, and
  `read:sprint:jira-software`. Adding classic scopes does not add these Jira
  Software scopes.

The console requests only the groups required by the selected objects and
access level. See Atlassian's
[Jira Cloud platform scope reference][jira-platform-scopes],
[Jira Software scope reference][jira-software-scopes], and
[refresh-token guide][atlassian-refresh-tokens].

## Configure the source

1. Open **Systems of Record → Overview**.
2. Choose an available vendor and select **Configure**.
3. In **System**, confirm the domain profile and vendor.
4. In **Connection**, follow the authentication path shown by the vendor:
   - For OAuth, copy the exact callback URL and register it in the vendor's
     OAuth application.
   - For Freshdesk, enter the exact `https://<site>.freshdesk.com` site URL and
     the API key from the account profile.
   - For a Notion API-key connection, enable read content and update content in
     the Creator dashboard. Enable read comments and insert comments when
     Agents may use `docs_comment`; Notion leaves comment capabilities off by
     default. Enter the internal integration token, then add the connection to
     only the intended pages or databases. The console repeats these
     prerequisites beside the credential field.
   - For Jira or Confluence, create an Atlassian OAuth 2.0 (3LO) app, register
     the exact callback shown by Eylo, and enter the exact
     `https://<site>.atlassian.net` origin. The authorizing account must be able
     to open that site. For Jira, configure the separate lifecycle, classic,
     and granular scope groups described above. The exact scopes appear beside
     every selectable source object before authorization.
   - For Linear, create an OAuth 2.0 app and register the exact callback. Eylo
     uses a Linear app actor; grant that app access only to the intended public
     or selected teams. Scheduled reconciliation works in local development
     without a public webhook endpoint.
   - For GitHub, create an OAuth App and register the exact callback. Enter each
     repository explicitly as `owner/repository`. After activation, an optional
     repository webhook can use the source-provided URL and secret for real-time
     updates; scheduled reconciliation remains available without it.
5. Complete any vendor-specific, non-secret source settings. GitHub requires
   one or more explicit `owner/repository` entries and will not infer every
   repository visible to the OAuth token. Intercom requires the workspace data
   region; choose US, EU, or AU rather than typing an arbitrary API URL.
   Confluence uses the site selected during Atlassian consent. Share only the
   required Notion pages or data sources with the chosen integration.
6. Select only the objects and read or read-write access the source needs.
7. For OAuth, enter the client ID and secret, save the app, authorize the
   vendor account, and return to Eylo. For Freshdesk or Notion API-key auth,
   select **Connect and verify**; Eylo makes one bounded authenticated request
   before storing the encrypted credential and source draft.
   The callback commits the provider connection before notifying the browser.
   If popup messaging is unavailable, the console checks the committed
   connection state after the window closes instead of treating the missing
   browser message as a failed authorization. If a resumable, unactivated
   source still references an older connection, the console rebinds it to the
   newly authorized connection before verification. An active source never
   changes accounts implicitly.
8. Verify the OAuth source. API-key sources perform this step as part of
   **Connect and verify**. Eylo persists the returned account identity and one
   immutable schema discovery.
9. In **Objects**, select the standard or discovered custom objects to sync.
   Each card repeats the provider scope required by that object; custom objects
   with no additional scope say so explicitly.
10. In **Field mapping**, map each selected field to one canonical field,
    one typed custom field, or ignore it.
11. In **Sync**, choose the freshness target and reconciliation interval.
12. Review **Webhooks**. Jira currently reconciles on a schedule; Linear
    supports verified webhook refetch. GitHub verifies repository webhook
    signatures, but the operator currently creates and removes the webhook in
    GitHub. Zendesk verifies signed ticket events; the operator currently
    creates and removes that webhook in Zendesk. Intercom verifies signed
    contact and conversation events; configure its callback and topics in
    Intercom Developer Hub. Confluence and Notion currently use scheduled full
    reconciliation and do not advertise webhook support.
13. In **Review**, resolve every blocker and activate the source.

Activation persists the published mapping, streams, and bootstrap work before
the durable worker starts. Closing the page after activation does not erase the
committed work.

The same public contract is available from the configured, authenticated CLI:

```bash
eylo sor actions
eylo sor get-catalog
eylo sor list-sources
```

Use the identifiers and body flags shown by `eylo sor actions` for source,
mapping, stream, grant, collection, and audit operations. The CLI calls the
public API and never bypasses source lifecycle or tenant checks.

OAuth client fields and API keys are held only in the open form and clear after
successful connection or **Start new**. Non-secret onboarding progress is
resumable; secret fields are never stored in the browser draft. **Start new**
discards the saved draft.

For Intercom, select only the permissions listed by the chosen streams and
tools in Developer Hub. Intercom permissions are app configuration, not an
OAuth URL `scope` parameter. Register Eylo's exact HTTPS callback URL in the
app. A US, EU, or AU workspace must use its matching consent and API region.

Freshdesk companies and native custom objects appear after verification as
audit-only custom datasets. Agents cannot read or mutate them through the
canonical Support tools in v1.

## Grant Agent access

1. Open the Agent draft and its **Relationships** section.
2. Grant the active source as read or read-write.
3. Add only the profile tools that Agent should use.
4. Publish the Agent.

Source configuration does not grant implicit Agent access. A running Agent uses
the tool and source-grant snapshot from its published revision.

For mutation tools, select the stream that owns the mutation result before
publishing the Agent:

- issue actions generally require the issue stream;
- `issue_comment` requires the comment stream and an active comment mapping;
- `issue_link` requires the issue-relation stream and an active relation mapping;
- `support_reply` and `support_add_note` require the comment stream and an
  active comment mapping;
- Documents create/update/append/comment actions require the page/document
  stream and its active mapping.

Eylo refuses the command before the vendor write if the declared result cannot
be projected. Related streams used for lookups do not replace this requirement.

## Audit the result

1. Open **Systems of Record → Sources** to check source state and sync health.
2. Open the profile collection, such as **CRM contacts**.
3. Search, filter, group, order, and choose visible columns.
4. Open a row to inspect canonical values, custom fields, source identity,
   mapping revision, freshness, and relationships.
5. For a Ticketing issue, inspect chronological comments in the detail drawer.
   **Not selected** means the source can provide the data but the stream is not
   enabled. **Unsupported** means the adapter does not provide that capability.
6. For a Document, inspect normalized text, hierarchy, unsupported source
   blocks, properties, versions, attachments, space, author, and original
   source links. An unsupported block was retained for audit, not understood
   as normalized document content.
7. Copy the URL to share the same audit view with another organization member.

Custom datasets are audit-only in v1. They show selected vendor-defined objects
that do not have canonical Agent semantics.

## Reauthorize or change a mapping

- Reauthorize when the source enters `REAUTH_REQUIRED`.
- Rediscover when the vendor schema changes.
- Publish a new mapping revision before expecting new fields in the projection.
- Run synchronization after the new mapping is active.

The last known projection remains visible while a source is degraded or a new
schema awaits mapping. Check its freshness before relying on it.

## Delete a source and its Eylo data

1. Open **Systems of Record → Sources**.
2. Choose **Delete** from the source row or source detail drawer.
3. Read the ownership boundary, then type the exact source name to confirm.

Eylo first disables the source so new sync, webhook, and Agent command work
cannot use it. Eylo then stops active durable work and permanently deletes the
source-owned local projection: synchronized records and relations, custom
fields and datasets, schema and mapping revisions, streams and sync history,
webhook and command receipts, and Agent source grants.

The reusable external connection remains available for another source. Eylo
does not delete, modify, or revoke data or credentials in the vendor account.
PII-safe durable action events already emitted by the source remain part of the
organization's event history.

The equivalent public API operation is:

```http
DELETE /api/{organization_id}/sor/sources/{source_id}
```

Success returns `204`. A missing source, another organization's source, or a
second delete returns `404`.

## Revoke access

- Delete an external connection to clear its stored credential and fence every
  dependent source.
- Remove an Agent source grant to stop that Agent's active source commands
  without changing another Agent's grant.

Both actions commit their authority change before asking the durable runtime to
stop exact tasks. Periodic SOR recovery closes a process-crash gap. A fenced
source keeps its last synchronized projection for audit, but no new or resumed
sync, webhook, or Agent command may use it.

[atlassian-refresh-tokens]: https://developer.atlassian.com/cloud/oauth/getting-started/refresh-tokens/
[jira-platform-scopes]: https://developer.atlassian.com/cloud/jira/platform/scopes-for-oauth-2-3LO-and-forge-apps/
[jira-software-scopes]: https://developer.atlassian.com/cloud/jira/software/scopes-for-oauth-2-3LO-and-forge-apps/
