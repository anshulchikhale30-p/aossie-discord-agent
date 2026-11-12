# AI Front Desk

## 1. Product Overview

AI Front Desk is a general-purpose conversational front desk connecting a service provider with its customers or participants. It handles operational questions, service information, appointments, meetings, reminders, announcements, and coordination between customers and the provider.

The product has two primary interaction sides: customer-facing and provider-facing. A provider may be an individual professional or an authorized team managing a business, organization, or multiple professionals and resources. The provider-facing side is one operational interface; individual professionals do not need separate front-desk conversations.

The system should handle routine requests while giving customers a clear path to an authorized person when information is missing or a matter requires human judgment.

The same product should support different service industries without separate industry-specific implementations. In healthcare settings, it is limited to service information and scheduling, not medical records or clinical decision-making.

The project also includes a hosted demonstration instance operated by the product team. Access must be limited to explicitly authorized demo accounts.

## 2. Core Interaction Model

Each configured messaging platform exposes its own bot or application identity. People can start a direct conversation with that identity or interact with the bot in other conversation contexts supported by the platform, such as groups, channels, or rooms, using native mechanisms such as mentions, commands, replies, or invitations. The same agent and capabilities serve these contexts; the product does not impose a universal DM-only or group-only boundary. Actual availability and message delivery depend on platform capabilities, app installation, permissions, and configuration. The bot processes messages directed to it or otherwise delivered under the integration's configured interaction rules; it does not treat unrelated messages as requests by default. The application remains authoritative for identities, permissions, operational records, and whether an action has succeeded.

The provider-facing side manages shared operational information and availability. Customers can access generally available provider information and manage only their own appointments and records.

## 3. User Roles

| Role | Capabilities | Access boundary |
|---|---|---|
| **Service provider and authorized staff** | Manage working hours, services, professionals and resources; view schedules and appointments; maintain operational information; answer escalated questions; configure reminders; request broadcasts; manage spam contacts; handle matters requiring human judgment. | One shared provider-facing interface, with access limited to the provider account and each staff member's authorization. |
| **Customer** | Ask operational questions; check availability; book, reschedule, or cancel appointments where permitted; view upcoming appointments; receive confirmations and reminders; confirm attendance; request clarification or human assistance. | Own verified customer records and information the provider makes generally available. |

Changing provider availability must not silently move or cancel an existing appointment. Affected customers are notified and offered valid alternatives.

## 4. Supported Channels

The initial planned messaging integrations are WhatsApp Business, Telegram, and Discord. Each integration has its own platform identity or addressable endpoint and maps supported interactions into the same application conversation model. Support direct conversations and other contexts, including groups, channels, or rooms, wherever the platform and integration provide them. Use each platform's native mechanisms for starting or addressing the bot; do not assume that mentions, invitations, or proactive messaging work identically across platforms. Available interactions and message delivery remain subject to platform capabilities, policies, permissions, and configuration.

## 5. Schedule Access and Scheduling

### 5.1 Conversational Schedule Access

Customers and providers can ask for appointments, schedules, and availability in natural language. The front desk presents the relevant information as readable text suitable for the messaging channel.

Customers see only their own appointments and availability relevant to their request. Providers see schedules within their authorized scope.

### 5.2 Availability and Booking Rules

The provider-facing side controls availability for the services, professionals, and resources it manages. Customers manage their own appointments within that availability.

A specific professional or resource is relevant when the service or booking requires one; the product does not assume that every conversation belongs to a particular professional.

A customer must choose and confirm a replacement when a provider's availability change affects an existing appointment. The system must not silently move or cancel the booking.

## 6. Notifications

Important operational events can generate the following notifications:

| Event | Front desk behavior |
|---|---|
| **Provider availability changes** | Identify affected appointments, notify the relevant customers, and offer valid alternatives. Each customer chooses whether to reschedule. |
| **Appointment or meeting created** | Send a confirmation to the relevant participants. |
| **Upcoming appointment or meeting** | Send reminders at provider-configured times, such as one day, 20 minutes, or 10 minutes before the event. The provider may request attendance confirmation. |
| **Customer declines or cannot attend** | Offer available alternatives and allow the customer to reschedule where permitted. |
| **Routine follow-up** | Support provider-recommended reminders after a specified interval, such as three or six months. |
| **Provider broadcast** | Send a provider-requested message to a defined customer group, such as an event, offer, or operational update. Adding or updating information does not automatically broadcast it. |

## 7. Provider Escalation and Human Handoff

### 7.1 Missing or Unreliable Information

When the front desk cannot answer confidently using the information available to it:

1. Tell the customer that the information is not currently available and that the provider will be asked.
2. Record the question as a pending request associated with the relevant provider, customer, and original conversation.
3. Notify the authorized provider through the provider-facing side.
4. Continue handling the customer's other messages and requests without waiting for the provider.

Pending questions are independent requests. Several questions from the same customer or different customers may remain open at the same time.

### 7.2 Customer Requests Clarification

A customer may ask for clarification when an answer is unclear, incomplete, incorrect, or unsatisfactory. This uses the same pending-question process and retains the original question, the answer already given, and the customer's clarification.

### 7.3 Urgent, Sensitive, or Unresolved Issues

Customers may request a human at any time. Complaints, suspected fraud, urgent incidents, technical support requests, and other matters requiring judgment or investigation should be routed to authorized staff through the existing provider-facing side.

The handoff should include an appropriate priority and a concise conversation summary so the customer does not need to repeat the issue. For emergencies or other time-critical risks, provide the appropriate verified emergency or official contact route. Do not imply that the agent has resolved the issue or promise an unconfirmed response time.

### 7.4 Provider Response and Follow-Up

The provider can answer a pending question with plain text through the provider-facing side. The front desk then:

1. Determines whether the response applies to the whole organization or only to the original customer.
2. Checks open pending questions that the new information may answer.
3. Ensures that each response is appropriate for the relevant customer's access scope.
4. Sends the answer through the original customer's conversation.
5. Resolves only the questions that have actually been answered; other questions remain pending.

A response to one customer's question is customer-specific by default. It becomes organization-wide information only when the provider confirms that it is generally applicable. Adding knowledge does not automatically trigger a broadcast.

## 8. Text-Based Operational Knowledge

### 8.1 Text-Only Input

Operational knowledge is entered directly as plain text through the provider-facing interaction. The system stores and uses text supplied by the provider.

Knowledge input is text-only. File uploads, document or archive processing, and ingestion of external files or repositories are outside the product scope.

### 8.2 Organization-Wide and Customer-Specific Information

Operational information is associated with the relevant service-provider account and, where applicable, a particular verified customer.

| Information scope | Applies to | Examples | Handling |
|---|---|---|---|
| **Organization-wide** | The relevant service-provider account. | Opening hours, shared policies, payment procedures, general booking rules. | Available across the account wherever the information applies. |
| **Customer-specific** | One identified, verified customer. | A private exception, individual arrangement, or answer to that customer's pending question. | Available only within that customer's authorized context. It does not become organization-wide unless the provider confirms that it applies generally. |
| **Professional, service, or resource context** | A relevant professional, service, location, or resource within either scope above. | Service-specific rules, resource restrictions, professional availability. | Used as applicability context, not as a separate general knowledge-scope category. |

Customer-specific information must not become organization-wide merely because it was supplied in response to a customer's question. When the intended scope is unclear, retain the narrower scope or ask the provider to clarify.

### 8.3 Accuracy and Validity

Operational information may be temporary or change over time. Retain the relevant effective dates, expiry dates, and cancellation details when the provider supplies them.

Do not present expired, cancelled, or outdated information as current. When applicable information conflicts or its validity is unclear, ask the provider rather than guessing.

## 9. Account and Customer Data Isolation

Each service-provider account is a separate data boundary. Its operational information, staff access, schedules, and customer records must not be exposed to another service provider.

Within an account, customer-specific information is associated with the correct verified customer and is not available to unrelated customers. Organization-wide information may be used across the account where it applies.

A person may interact with multiple service providers. Their records for each provider remain separate unless the person completes an explicit, trusted identity-linking process. A shared name or messaging identifier alone is not sufficient reason to merge records.

Individual professionals and resources are distinguished when needed for scheduling, assignment, or access, without requiring a separate front-desk interface for each one.

## 10. Spam Management

Providers can mark a contact as spam, view the blocked contacts, and remove a contact from the spam list.

Once blocked, a contact should no longer be processed for normal requests or receive ordinary outbound messages. Blocking a contact does not cancel their appointments, delete their customer record, or remove historical service information. Those are separate actions.

## 11. Functional Requirements

The front desk must support the following provider-facing and customer-facing capabilities across the planned messaging channels and the conversation contexts supported by each integration.

| Functional area | Required capabilities |
|---|---|
| **Provider-facing operations** | Manage working hours, service availability, professionals and resources; view schedules and appointments; maintain operational information; answer pending questions; configure reminders; request broadcasts; manage spam contacts; route matters requiring human judgment. The provider-facing side is one shared interface for the provider and authorized staff. |
| **Customer-facing operations** | Ask about provider-supplied information, services, policies, events, and availability; view their own appointments; request bookings, rescheduling, and cancellations where permitted; receive confirmations, schedule-change notices, reminders, and announcements; confirm attendance; request clarification or human assistance; receive later answers in the original conversation. |
| **Scheduling and booking** | Support appointments, consultations, meetings, and other provider-defined scheduled services. Show date, time, timezone, service, and professional/resource details before confirmation. Revalidate availability when committing a booking, prevent conflicts, preserve the existing booking until a replacement is confirmed, and let affected customers choose alternatives after provider availability changes. |
| **Operational knowledge** | Accept provider-supplied plain text only. Support organization-wide and customer-specific information, with professional, service, or resource context where applicable. Keep customer-specific answers private unless the provider confirms general applicability. Track source and validity sufficiently to distinguish current, expired, cancelled, and superseded content. |
| **Knowledge input boundaries** | File uploads, document extraction, external URL ingestion, repository ingestion, and automatic external catalog crawling are outside the current scope. |
| **Escalation and follow-up** | Create pending questions when authorized information is missing, unreliable, conflicting, or insufficient. Acknowledge the customer and notify the provider without blocking other interactions. Match provider answers to eligible pending questions, reply in the original conversation, resolve only answered questions, and route urgent, sensitive, or unresolved matters to authorized staff with priority and a concise summary. |
| **Notifications and channels** | Send booking confirmations, configurable reminders, attendance requests, and provider-defined follow-ups. Notify customers of availability changes, support rescheduling, and allow provider-requested broadcasts. Preserve the originating conversation or intended recipient when replying or sending notifications. Support direct and shared conversation contexts where each platform integration allows them; outbound initiation and delivery must follow platform capabilities, permissions, consent, and policies. Retry failed delivery without repeating the business action. Planned channels are WhatsApp Business, Telegram, and Discord. |
| **Hosted demonstration** | Provide a hosted demonstration instance restricted to explicitly authorized demo accounts. It must not expose an unrestricted public environment or another tenant's data. |

## 12. Non-Functional Requirements

The product must protect provider and customer data and preserve correct business state during concurrent activity, retries, delayed responses, restarts, and temporary service failures.

| Area | Requirement |
|---|---|
| **Tenant and customer isolation** | Each provider account is a strict data boundary. The authenticated application context determines tenant, provider/staff, customer, and resource identity. Recheck authorization for requests, tool calls, callbacks, resumed workflows, and scheduled operations. Keep a person's records separate across providers; link identities only through trusted verification. |
| **Application-controlled access** | The model must not receive database credentials, unrestricted database access, or authority to select arbitrary tenant or customer identifiers. Route reads and mutations through narrowly scoped application services that validate identity, authorization, record ownership, input, and current business state. Model instructions, tool arguments, and confidence are not security boundaries. |
| **Booking and state consistency** | Revalidate and claim availability atomically when committing a booking; only one conflicting booking may succeed. Reject stale slots and offer current alternatives. When provider changes affect existing bookings, let each customer choose a replacement. Blocking a contact does not cancel appointments or delete customer records. |
| **Duplicate events and idempotency** | Account for duplicate and out-of-order messages or webhook events. Deduplicate using the tenant, channel connection, and external event identifier where available. Recheck state before mutations and ensure retries do not repeat bookings, cancellations, rescheduling, broadcasts, or availability changes. |
| **Durable work and message delivery** | Pending questions, reminders, broadcasts, and deferred notifications must persist and recover after restarts. Scheduled work rechecks current business state before acting. Commit business changes independently of outbound delivery; retry delivery without reversing successful operations or repeating their effects. Process large broadcasts and long-running work in bounded, resumable tasks. |
| **Provider authorization and resilience** | Require authorization or confirmation for provider actions with broad impact, such as large broadcasts or availability changes affecting existing bookings. AI, workflow, or messaging failures must not corrupt operational records. If a mutation's result cannot be confirmed, do not claim success; retain enough state to retry or recover incomplete work. |
| **Context quality and sensitive information** | Supply the agent only with bounded information authorized for the current tenant and customer. Do not present expired or superseded information as current; escalate missing, ambiguous, or conflicting information. Customer-specific information must not broaden into organization-wide knowledge without provider confirmation. In healthcare settings, support service information and scheduling only; do not access medical records, diagnose, or provide clinical advice. |
| **Time and timezone handling** | Store appointment and due-work timestamps consistently and retain the provider's timezone for interpretation and display. Apply timezone and daylight-saving calculations in application logic. Resolve relative dates against the original message timestamp and provider timezone; ask when genuinely ambiguous. |

## 13. Technical Architecture

| Area | Responsibility |
|---|---|
| **Application endpoints (when needed)** | Use Next.js with file-based routing for server-side endpoints when a provider-built client or external integration requires them. This does not define a separate API product or include a project-provided web chat client. |
| **Application and domain services** | Shared TypeScript application services own authentication, authorization, tenant/customer isolation, business rules, validation, and authoritative state changes. Next.js endpoints, where needed, EVE tools, and messaging integrations use the same services so conversations and external operations cannot diverge in business behavior. Keep framework and channel adapters thin. |
| **Agent runtime** | EVE owns agent/session execution, model interaction, messaging channels, tool calling, approvals, subagents, and durable agent workflows. It invokes approved application services; it does not replace the product data-access layer or authoritative application records. |
| **Scoped operations** | Expose application operations for schedules, bookings, customer records, operational knowledge, reminders, broadcasts, spam management, and provider escalation. The authenticated conversation context supplies identity and access scope. EVE tools and messaging integrations use these operations. |
| **Database and data access** | PostgreSQL stores authoritative provider, customer, schedule, booking, knowledge, pending-question, reminder, and delivery records. Locally and in standard CI tests, the application connects to Azure Database for PostgreSQL Flexible Server through Floci AZ; do not run a separate local PostgreSQL service by default. Azure validation uses the managed Azure Database for PostgreSQL service. Drizzle ORM is the preferred data-access option. |
| **Operational knowledge** | Store provider-supplied plain text with organization-wide or customer-specific scope, plus source, applicability, and validity information. Apply authorization and scope filtering before supplying context to the agent. Retrieve live availability and bookings through application operations, not copied knowledge text. |
| **Messaging integrations and conversation context** | Connect through each platform's bot/application identity or addressable endpoint. Map direct messages and supported groups, channels, or rooms into the shared conversation model using platform-native interaction mechanisms. Keep a separate context for each platform conversation; do not impose a product-wide DM-only or group-only boundary. Each adapter exposes only the interaction types the platform supports. |
| **Identity resolution** | Resolve the receiving platform connection and conversation to the owning provider account before resolving the sender. Keep external sender identifiers scoped to their platform connection, keep customer identities separate across providers, and require trusted verification to link identities. Enforce participant and tenant permissions for every conversation context. |
| **Container deployment** | Package the application and required runtime processes as prebuilt, versioned container images. Kubernetes workloads run on K3s and are deployed through Flux CD. |
| **Kubernetes configuration** | Use Kustomize bases and overlays for declarative Kubernetes configuration across local and CI environments. Flux CD reconciles the GitHub-defined configuration. |
| **Floci container execution bridge** | Floci AZ's container-backed services require a Docker-compatible container API. Use KubeDock as Floci AZ's remote container API endpoint so supported container requests are translated into short-lived K3s Pods and Services. KubeDock is an API-compatibility bridge, not Docker Engine. Docker Engine, Docker daemon, Docker socket, Docker-in-Docker, and Docker Compose are not used or required anywhere in the development, CI, or runtime stack. Use KubeDock only for Floci-managed ephemeral sidecars and test engines, not long-running application workloads or persistent databases. Its supported API subset, TCP-only service networking, and non-durable volume semantics must be respected. Keep its API cluster-internal behind a ClusterIP Service, restrictive NetworkPolicy, scoped RBAC, and isolated test namespaces. |
| **Background processing** | Run reminders, broadcasts, schedule-change notifications, provider follow-ups, and delivery retries as durable background work. Scheduled operations must survive restarts, recheck current business state, and avoid duplicate effects. |
| **State ownership** | PostgreSQL remains authoritative for product records and business state. Agent/workflow runtime state supports execution and recovery but does not replace application records or prove that a database mutation or external message delivery succeeded. |

## 14. Preferred Technology Stack

The preferred stack and the responsibility of each part are:

| Area | Preferred technology | What it covers |
|---|---|---|
| Application endpoints (when needed) | [**Next.js**](https://nextjs.org/docs) | Optional server-side endpoints for provider-built clients and external integrations, using file-based routing. No bundled web chat client or predefined API specification. |
| Agent framework | [**EVE**](https://github.com/vercel/eve/tree/main/docs) | Agent and session execution, tool calling, durable workflows and scheduling, human-in-the-loop approvals, subagents, external connections, model integration and routing, and sandboxed execution. Messaging channels include first-class EVE channels such as Discord and Telegram; WhatsApp Business can be connected through the Chat SDK channel and its WhatsApp adapter. Actual availability depends on current EVE/adapter support, platform requirements, credentials, and capabilities. EVE brings together the relevant Vercel agent capabilities, including AI SDK, AI Gateway, Chat SDK, Vercel Connect, Workflows, and Sandbox; these are not separate stack selections. |
| Application and domain services | [**TypeScript**](https://www.typescriptlang.org/docs/) | Shared authentication, authorization, tenant/customer isolation, business rules, validation, integrations, and authoritative application operations used by EVE tools and messaging integrations. |
| Database | [**PostgreSQL**](https://www.postgresql.org/docs/) and [**Azure Database for PostgreSQL Flexible Server**](https://floci.io/floci-az/services/postgresql/) | Persistent relational storage. Local development and standard CI tests use the PostgreSQL service exposed through Floci AZ; Azure validation uses the corresponding managed Azure service. |
| Data access | [**Drizzle ORM**](https://orm.drizzle.team/docs/overview) | Preferred ORM/data-access layer for PostgreSQL. |
| Kubernetes configuration | [**Kustomize**](https://kustomize.io/) | Declarative Kubernetes bases and environment/test overlays consumed by Flux CD. |
| Kubernetes runtime | [**K3s**](https://docs.k3s.io/) | Required Kubernetes environment for local development, CI/CD deployment tests, and the corresponding Azure VM/VPS deployment target. Uses containerd for workload execution. |
| Floci container API bridge | [**KubeDock**](https://github.com/joyrex2001/kubedock) | Supplies Floci AZ with a Docker-compatible API endpoint by translating supported container lifecycle calls into ephemeral Kubernetes Pods and Services. It is not Docker Engine and does not require Docker to be installed or run. Use only for Floci-managed disposable sidecars/test engines, not persistent services or production application workloads. |
| Infrastructure provisioning | [**Crossplane**](https://docs.crossplane.io/latest/) | Required Kubernetes-oriented provisioning and management of infrastructure through Floci AZ locally and in CI, and through Azure in Azure validation. |
| GitOps deployment | [**Flux CD**](https://fluxcd.io/flux/) | Required GitOps deployment and reconciliation. Flux CD watches the GitHub repository and applies the version-controlled Kubernetes/Kustomize and Crossplane desired state in local, CI, and Azure K3s environments. |
| Azure API emulation | [**Floci AZ**](https://github.com/floci-io/floci-az) | Required local and CI Azure service emulator for the Azure-compatible APIs implemented by the pinned release. Configure its container-backed services to use KubeDock rather than Docker Engine, a Docker daemon, or a host socket. |

The deployment tools above are mandatory parts of the selected architecture, not optional alternatives. Their exact versions, provider configuration, and environment-specific values can be settled during implementation without changing the required deployment path.

## 15. Mandatory Local-to-Cloud Deployment Parity

**Priority: Mandatory.** Local development, CI/CD testing, and Azure validation must follow the same deployment architecture and control plane. Local development is primarily for testing, but it must not use a separate simplified runtime that bypasses the intended infrastructure.

The required toolchain is **Floci AZ, K3s, Crossplane, and Flux CD**. K3s provides the Kubernetes runtime; Crossplane provisions infrastructure; Flux CD deploys and reconciles the GitHub-defined desired state; Floci AZ supplies the local Azure-compatible services where its supported service emulation is available.

### 15.1 Required deployment path in every environment

| Component | Local machine | CI/CD testing | Azure validation |
|---|---|---|---|
| Azure services | Run Floci AZ and connect application services to its supported Azure-compatible endpoints. | Start Floci AZ as part of the pipeline and use its supported Azure-compatible endpoints for integration tests. | Use the corresponding real Azure services and endpoints. |
| Kubernetes | Run K3s locally; do not bypass it with host-run application services. | Create/use a K3s test cluster for deployment and integration tests. | Use the corresponding K3s deployment on the Azure VM/VPS target. |
| Infrastructure provisioning | Run Crossplane in the local K3s environment and configure its Azure provider connection to Floci AZ. | Run Crossplane in the CI K3s environment against Floci AZ for emulated-resource provisioning. | Run Crossplane against Azure to provision and manage the Azure resources required for validation. |
| GitOps and deployment | Run Flux CD in local K3s. It must watch the GitHub repository and reconcile the committed manifests and Crossplane desired state. | Run Flux CD in the CI K3s environment and deploy from the same GitHub source of truth. | Run Flux CD in the Azure K3s environment and reconcile the same version-controlled deployment definitions. |
| Application packaging | Deploy prebuilt, versioned container images. | Use the same prebuilt image artifacts produced by the pipeline; do not build application source inside Kubernetes. | Deploy the same versioned image artifacts used in local and CI Kubernetes tests. |
| PostgreSQL | Connect only through the PostgreSQL Flexible Server service exposed by Floci AZ. | Use the PostgreSQL service exposed by Floci AZ for standard integration tests. | Use Azure Database for PostgreSQL Flexible Server. |

Crossplane and Flux CD are required in all three stages. They must not be skipped in local testing or CI in favor of manual resource creation, direct \`kubectl\`-only deployment, or a different deployment tool. The same Crossplane compositions and Flux-managed GitHub desired state should be carried through each stage, with only the environment-specific provider endpoint, credentials, secrets, and resource values changed.

### 15.2 PostgreSQL handling

PostgreSQL must be accessed through Floci AZ for local development and standard CI integration tests. Use Floci AZ's Azure Database for PostgreSQL Flexible Server service and the connection information it exposes.

Do not start a separate PostgreSQL container, host service, or Kubernetes pod for normal local development or standard CI testing. Floci AZ manages the local PostgreSQL engine behind its Azure-compatible service endpoint.

A PostgreSQL pod in K3s is permitted only as an explicit, test-specific fallback when a persistence or recovery test cannot be performed through the Floci AZ PostgreSQL service. It is not the default local database and must not silently replace Floci AZ. Azure validation uses the actual managed Azure Database for PostgreSQL Flexible Server service.

Keep the PostgreSQL major version, schema migrations, connection behavior, and application data-access path aligned between Floci AZ testing and Azure validation. Record and test material emulator differences, including any local-only TLS or persistence behavior.

### 15.3 CI/CD and parity requirements

Every CI/CD validation run that tests deployment behavior must:

1. Start Floci AZ and make its required Azure-compatible services available.
2. Create or use a K3s test cluster.
3. Install and configure Crossplane to provision the Floci AZ-backed resources used by the test.
4. Install and configure Flux CD to watch the GitHub repository and deploy/reconcile the committed desired state.
5. Deploy the prebuilt application images and run integration tests against the deployed services, including the Floci AZ PostgreSQL endpoint.
6. Run Azure validation using Crossplane and Flux CD against the corresponding Azure environment, including the managed PostgreSQL service where applicable.

Unit tests may still run independently, but they do not replace the required Floci AZ + K3s + Crossplane + Flux CD deployment and integration path. A green unit-test run alone is not evidence of deployment parity.

No environment may silently substitute an unrelated local PostgreSQL instance, manual infrastructure setup, or a separate CI-only deployment toolchain for the required path. Any genuine difference between Floci AZ and Azure must be recorded and validated against the real Azure service.

References:
- [K3s documentation](https://docs.k3s.io/)
- [Crossplane documentation](https://docs.crossplane.io/latest/)
- [Flux CD documentation](https://fluxcd.io/flux/)
- [Floci AZ](https://github.com/floci-io/floci-az)
- [Floci AZ Azure Database for PostgreSQL emulation](https://floci.io/floci-az/services/postgresql/)

## 16. Example Use Cases

These are applications of the same general-purpose front desk, not separate products or separate architectures. The examples illustrate the actual customer-facing and provider-facing workflows, including knowledge, scheduling, escalation, notifications, and follow-up.

### 16.1 Clinic Front Desk

**Interfaces**

- **Patient-facing:** Patients message the clinic through WhatsApp or Telegram to ask questions and manage appointments.
- **Provider-facing:** Authorized clinic staff use the provider-facing side to update availability, supply plain-text operational information, answer escalated questions, and request announcements.

**Example workflow**

1. **Add operational context.** Staff tell the agent: "We are hosting a patient orientation event next Saturday at 3 PM in Hall B," or provide the details of a time-limited service offer. The agent records the information with the resolved date, location, conditions, and validity period. Staff may update or cancel the information later.
2. **Answer patient questions.** A patient asks through the clinic's messaging channel about the venue, event timing, available services, offer eligibility, opening hours, payment procedures, or appointment availability. The agent answers using current authorized text and live schedule data from the application. Once an event has passed or an offer has expired, it explains that the information is no longer current.
3. **Escalate without blocking.** If the information is missing, conflicting, or insufficient, or the patient finds an answer unsatisfactory, the agent records a pending question, tells the patient it will check with staff, and continues handling other requests. Staff later provide a plain-text clarification through the provider-facing side. The agent returns the answer to the original patient and checks whether the same information resolves other eligible pending questions, while preserving customer-specific access boundaries.
4. **Notify when instructed.** Staff can ask the agent to announce the event, offer, or changed schedule to an appropriate group of patients. The announcement is sent through the configured messaging channel after the provider has requested it; adding or updating knowledge does not automatically broadcast.
5. **Coordinate appointments.** Patients book, cancel, or reschedule within staff-defined availability. If availability changes, affected patients are notified and offered valid replacement slots. The patient chooses whether to reschedule.
6. **Send timed reminders.** The agent sends appointment confirmations, configurable reminders, attendance requests, and provider-specified follow-up reminders.

**Boundary:** This workflow handles front-desk operations and service information, not medical records, diagnosis, or clinical advice.

### 16.2 Organization Front Desk (Discord Example)

This is an example deployment of the general-purpose bot, not a product-defined Discord interaction model. The server owner or administrators decide whether to add the bot, which public or private channels it can access, who can use it, and how members are introduced to it. Members can also contact the bot directly through its Discord identity. Any server-wide onboarding or member-DM workflow is an optional deployment choice controlled by the server administrators and subject to Discord's capabilities and policies.

**Example workflow**

1. **Configure the organization deployment.** The server administrators choose where the bot is available and how contributors discover or start conversations with it. Maintainers provide organization instructions, project information, policies, event details, and contributor guidance as plain text. The information is stored with organization-wide or customer-specific scope as appropriate.
2. **Answer contributor questions.** A contributor asks through an available Discord conversation how to set up a project, where to find a policy, what events are coming up, how to participate, or when a maintainer is available. The agent answers using the authorized text information and current schedule data.
3. **Escalate and keep the conversation active.** If the answer is unavailable or the contributor considers it unsatisfactory, the agent acknowledges the pending follow-up, records the question, and asks an authorized maintainer through the provider-facing side. The contributor can continue asking other questions or scheduling meetings without waiting.
4. **Provide a later answer.** The maintainer supplies a plain-text explanation. The agent stores it with the appropriate scope, identifies which open questions it actually answers, and replies in the original Discord conversation. Questions not addressed remain pending.
5. **Manage events and announcements.** A maintainer says: "We have a contributor onboarding session one week from now at 6 PM," supplies the venue or meeting link as text, and optionally asks the agent to notify the relevant audience. The date is resolved when the context is added. Subsequent questions receive the correct upcoming, cancelled, or past-event status.
6. **Coordinate meetings.** Contributors request time with a maintainer or mentor through Discord. The agent shows valid availability, handles booking and rescheduling, and notifies the relevant participants of changes.
7. **Send reminders.** Scheduled notifications remind the contributor and maintainer 10 or 20 minutes before their meeting, according to the configured reminder rules.

### 16.3 Provider-Hosted Website Chat Client

A provider may independently build and host a chat client on its website and connect it to the AI Front Desk chatbot through an integration they implement using the available connection interfaces. The website UI, client, hosting, and deployment are provider-managed and are not part of this project.

### 16.4 Scheduling and Reservation Management Examples

The same scheduling capability can coordinate people, time slots, sessions, and resources across different service domains.

| Domain | Illustrative operations |
|---|---|
| Appointments and consultations | Schedule appointments and move them to another available time slot |
| Meetings and mentorship | Schedule meetings, reschedule them, and notify participants |
| Classes and workshops | Manage session schedules and move participants to sessions with available capacity |
| Hotels and accommodation | Change reservation dates when suitable rooms are available |
| Vehicle and equipment rentals | Modify rental periods based on resource availability |
| Venues and meeting rooms | Reschedule reservations or move them to another available space |
| Tours and experiences | Change reserved dates, times, or sessions where permitted |
| Other scheduled services | Apply provider-defined scheduling and reservation rules |

These examples illustrate how the general scheduling capability may be applied; they do not imply that every external reservation platform or domain-specific integration is already connected.

The initial generalized behavior centers on the appointment and meeting operations described in this specification. Additional reservation domains can use the same concepts of authorization, availability, resource allocation, and confirmation when their business rules and required integrations are implemented.

All changes must respect authorization, availability, applicable conditions, and the connected system's capabilities. The original reservation must remain unchanged if a requested modification cannot be completed successfully.

## 17. Future Extension: Social Media Marketing Agent

A separate, optional Social Media Marketing Agent may be built on top of AI Front Desk. It would help service providers promote selected products or projects through relevant public conversations while reusing approved public information and the existing provider-escalation workflow.

### 17.1 Proposed Workflow

1. The service provider selects the products or projects to represent and authorizes the social accounts to be used, such as X and Reddit.
2. The marketing agent discovers public posts and discussions that are genuinely relevant to those products, projects, or the problems they address.
3. Before engaging, it checks relevance, platform and community rules, prior interactions, and duplicate post or comment identifiers.
4. It prepares a grounded response using information the provider has approved for public disclosure. Initially, replies to discovered posts require provider review and approval before publication.
5. It tracks replies to permitted published comments. Previously verified answers may be reused where appropriate; new or unclear questions can be escalated through the existing provider workflow.
6. When the provider supplies missing information, the marketing agent can prepare an appropriate follow-up, subject to the required approval and platform rules.

### 17.2 Boundaries

- Social discovery, interaction tracking, review, and posting belong to the Social Media Marketing Agent. AI Front Desk remains responsible for provider-approved information and provider escalation.
- Only information explicitly approved for public disclosure may be used. Customer-specific information and private conversations must never appear in social replies.
- Posting and replies must comply with each platform's permissions, automation policies, rate limits, and community rules. Discovering a relevant post does not itself authorize a promotional reply.
- Keep enough interaction history to avoid duplicate or repetitive engagement.
- This is a future extension, not part of the core AI Front Desk product scope.


