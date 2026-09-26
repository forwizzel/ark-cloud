# Ark Cloud — Personal Cloud Control Plane

> **Historical project brief.** The Phase 0 assignment and numbered phase proposals below are
> retained for context. For current implementation status and phase numbering, use
> [README.md](README.md) and [docs/roadmap.md](docs/roadmap.md).

You are acting as the senior software engineer, systems architect, DevOps engineer, and technical mentor for a new project called **Ark Cloud**.

Your job is to help me build this system incrementally while maintaining production-quality architecture, security practices, documentation, and code quality.

Do not attempt to build the entire project in one pass.

Version 0.3 includes local single-user sessions, infrastructure status, a metadata-only connection
to Google Drive as the designated user-content storage provider, and a principal-scoped Drive
catalog with filename search. Treat completed phases as the foundation for later work rather than
rebuilding them.

---

# 1. Project Vision

Ark Cloud is a **self-hosted personal cloud control plane**.

The eventual goal is to provide one centralized web interface through which I can view, manage, search, and monitor my personal infrastructure and data.

It should eventually unify things such as:

- Personal file storage
- Photo storage
- Password-vault status
- Tailscale network/device status
- Server health
- Container/service status
- Backup health
- Notifications
- Activity history
- Personal notes
- Search across supported services

The project should NOT unnecessarily reinvent mature technologies.

Ark Cloud should primarily act as:

- a control plane
- an integration layer
- a unified dashboard
- an API gateway for personal services
- an observability interface
- an extensible platform

Specialized applications should remain responsible for specialized functions where appropriate.

Examples:

- Immich → photo management
- Vaultwarden/Bitwarden → passwords
- Tailscale → private networking
- Ark Cloud → unified interface over all of them

Think of Ark Cloud as a miniature personal version of something conceptually similar to a cloud-provider management console.

---

# 2. Existing Infrastructure

My environment already includes a dedicated Linux development/server machine named:

**Ark**

Ark currently runs Fedora Linux.

Ark is intended to become an always-on or semi-headless development and self-hosting server.

Existing infrastructure includes:

- Fedora Workstation
- SSH
- VS Code Remote SSH
- tmux
- Git
- GitHub access
- Tailscale
- Wake-on-LAN
- Ethernet networking
- Reserved/stable network configuration
- Sleep/hibernate disabled
- A Windows desktop that acts as my primary computer
- iPhone Tailscale access

I can currently connect to Ark remotely through Tailscale and SSH.

The ideal long-term access model is:

Windows / Laptop / iPhone
        ↓
    Tailscale
        ↓
       Ark
        ↓
    Ark Cloud

Ark Cloud should not require public Internet exposure.

Avoid opening public router ports unless there is a compelling future reason.

---

# 3. Important Development Philosophy

This is both a real project and a learning project.

I am a computer science student learning:

- Linux
- backend development
- APIs
- Docker/containers
- networking
- distributed systems
- infrastructure
- platform engineering
- DevOps
- observability
- system design
- security

Do not hide important implementation details from me.

When introducing:

- shell commands
- command-line flags
- Docker commands
- networking concepts
- configuration files
- infrastructure decisions

briefly explain what they do.

For example, if using:

`docker run -p 8000:8000`

explain what `-p` means.

Do not excessively explain basic syntax every time after a concept has already been covered.

Favor understanding over blindly copying commands.

---

# 4. High-Level Architecture

Ark Cloud should eventually resemble:

```text
                    Clients

        Windows / Laptop / Phone
                    │
                Tailscale
                    │
                    ▼
             ┌──────────────┐
             │  Ark Cloud   │
             │  Web Client  │
             └──────┬───────┘
                    │
                  HTTPS
                    │
             ┌──────▼───────┐
             │ Ark Cloud API│
             │              │
             │ Auth         │
             │ Integrations │
             │ Search       │
             │ Events       │
             │ Notifications│
             └──────┬───────┘
                    │
       ┌────────────┼────────────┐
       │            │            │
       ▼            ▼            ▼

    Tailscale     Immich      Vaultwarden
       API          API          status/API

       │
       ├──────────────┐
       ▼              ▼

 System Agent     Google Drive
```

This will evolve over time.

Do not tightly couple the frontend to individual services.

---

# 5. Core Architectural Requirement: Integrations

Ark Cloud must have an integration/connector abstraction.

Do NOT scatter service-specific logic throughout controllers or UI components.

Create an architectural concept similar to:

```text
Integration
    health()
    summary()
    activity()
    search()
```

Individual adapters may eventually include:

```text
TailscaleIntegration
SystemIntegration
StorageIntegration
ImmichIntegration
VaultIntegration
BackupIntegration
DockerIntegration
```

Not every integration must implement every optional capability.

Design this in a way that remains simple initially but can grow later.

Avoid overengineering a complex plugin framework before it is needed.

A clean interface/service abstraction is sufficient for Version 0.1.

---

# 6. Preferred Initial Technology Stack

Unless there is a strong technical reason otherwise, start with something similar to:

Frontend:

- React
- TypeScript
- Vite

Backend:

- Python
- FastAPI

Database:

- PostgreSQL

Infrastructure:

- Docker
- Docker Compose

Reverse proxy later:

- Caddy or another appropriate lightweight reverse proxy

API style:

- REST initially

Possible later technologies:

- Redis
- WebSockets
- background workers
- message queues

Do NOT introduce those until the application actually needs them.

Favor the simplest architecture capable of evolving.

If you believe a stack choice should change, explain the tradeoff before making a major change.

---

# 7. Repository Strategy

Prefer a monorepo initially.

A possible structure:

```text
ark-cloud/
│
├── apps/
│   ├── web/
│   └── api/
│
├── packages/
│
├── infrastructure/
│
├── docs/
│
├── scripts/
│
├── tests/
│
├── .env.example
├── .gitignore
├── docker-compose.yml
├── README.md
└── LICENSE
```

Adjust this structure if there is a cleaner solution.

Keep infrastructure and application code clearly separated.

Do not create directories with no immediate purpose just to make the repository look sophisticated.

---

# 8. Version Roadmap

The following is the intended roadmap.

Do not implement all of this immediately.

---

## Phase 0 — Foundation

Goal:

Create a clean development environment and architectural foundation.

Deliverables:

- Git repository structure
- Backend skeleton
- Frontend skeleton
- PostgreSQL service
- Docker Compose development environment
- `.env.example`
- configuration management
- basic logging
- `/health` backend endpoint
- frontend health/status page
- backend ↔ frontend connectivity
- database connectivity
- project README
- architecture documentation
- development instructions
- initial tests
- linting/formatting
- GitHub-ready repository

The application should start with one documented command or a very small number of commands.

Example:

```bash
docker compose up
```

or an equally straightforward development workflow.

At the end of Phase 0, I should be able to open Ark Cloud in my browser and see that:

- frontend is running
- backend is healthy
- database is connected

---

## Phase 1 — Ark Cloud v0.1

Primary features:

### Dashboard

Create the first useful dashboard.

Display:

- Ark status
- uptime
- CPU utilization
- RAM utilization
- storage usage
- basic service health

### System Integration

Create an Ark system monitoring integration.

Possible data:

- hostname
- OS
- kernel
- uptime
- CPU utilization
- memory usage
- disk usage
- network information

Prefer standard Linux interfaces/libraries where reasonable.

Avoid requiring root privileges unless absolutely necessary.

Consider whether metrics should be gathered:

- directly by the API
- through a separate local agent

For v0.1, choose the simpler safe implementation.

Document how this could later become a dedicated agent.

### Tailscale Integration

Integrate Tailscale device information.

Eventually display:

- device name
- online/offline status
- Tailscale IP
- operating system
- last seen
- tags if useful

Never commit API credentials.

Use environment variables or an appropriate secrets mechanism.

### Service Health

Introduce the integration abstraction.

Dashboard should be able to ask each integration:

```text
Are you healthy?
What is your summary?
```

---

## Phase 2 — Google Drive Control Plane (v0.2)

Integrate Google Drive as the existing personal file-storage system rather than building custom
storage.

Deliverables:

- local single-user session authentication with CSRF protection
- server-side Google OAuth web flow
- encrypted refresh-token persistence
- normalized connected-account and storage-quota status on the dashboard
- direct link to Google Drive for all file operations

Security requirements:

- keep OAuth client credentials and refresh tokens server-side
- request metadata-only Drive access
- validate OAuth state against the local session
- never expose raw upstream responses or proxy file content

Google Drive remains the file manager and source of truth. Do not add folder browsing, uploads,
downloads, rename, delete, move, export, or content proxies to Ark Cloud.

PostgreSQL remains the control-plane store for sessions, encrypted credentials, connection state,
and derived metadata. It must not become a duplicate user-content store.

---

## Phase 3 — Drive Catalog and Unified Search

Build a searchable control-plane catalog from normalized Google Drive metadata without copying
file content into Ark Cloud.

Status: implemented in Version 0.3 for My Drive metadata and filename search.

Deliverables:

- authenticated, principal-scoped Drive metadata catalog
- metadata search with pagination and normalized results
- direct links to Google Drive for file operations
- reviewed synchronization, indexing, and stale-data behavior
- PostgreSQL storage only for derived metadata and search indexes, never file bodies

Keep Google credentials, access tokens, and raw upstream payloads server-side. Review the minimum
OAuth scopes before implementation, and do not add uploads, downloads, destructive file actions,
or content proxies as part of this phase.

Future integrations may contribute safe results to unified search after their own security review.
Never place secrets in the general search index.

---

## Phase 4 — Photo Platform

Do NOT build an entire photo platform ourselves.

Integrate a mature self-hosted photo system such as Immich.

Ark Cloud should act as a control plane over it.

Potential dashboard features:

- photo count
- recent uploads
- albums
- storage usage
- Immich health
- latest photos

Potential future unified search results:

```text
Search: "Florida"

Photos
- beach.jpg
- sunset.jpg

Files
- Florida Trip.pdf
```

Keep Immich authentication/secrets isolated from the browser where practical.

---

## Phase 5 — Backups

Add first-class backup monitoring.

Backups are extremely important because Ark Cloud will eventually contain valuable personal information.

Potential technologies may include:

- restic
- BorgBackup
- rsync

Choose based on requirements when this phase begins.

Dashboard should eventually report:

```text
Backups

Ark Files
Last backup: 2 hours ago
Status: Healthy

Photo Library
Last backup: 4 hours ago
Status: Healthy
```

Potential future functionality:

- backup history
- storage destination
- backup size
- failed backup alerts
- restoration testing status

A backup system is not complete unless restoration is documented and testable.

---

## Phase 6 — Password Vault

DO NOT implement custom password cryptography.

Use an established password manager such as:

- Vaultwarden
- Bitwarden

Ark Cloud should initially expose only safe metadata such as:

```text
Vault
Status: Healthy
Backup: Healthy
Open Vault →
```

Ark Cloud should NOT initially retrieve or display plaintext passwords.

Any deeper integration involving sensitive secrets requires explicit architectural review.

---

## Phase 7 — Unified Activity System

Introduce a normalized event model.

Examples:

```text
14:21 Laptop connected to Tailscale
14:03 16 photos uploaded
13:40 Backup completed
12:11 Container restarted
```

Possible event fields:

```text
id
source
type
severity
message
timestamp
metadata
```

Integrations should eventually be capable of producing events.

Dashboard displays a unified activity feed.

---

## Phase 8 — Container / Service Management

Add awareness of services running on Ark.

Potential information:

- running containers
- health
- uptime
- image
- port bindings
- restart count

Possible UI:

```text
Services

Ark Cloud API      Healthy
PostgreSQL         Healthy
Immich             Healthy
Vaultwarden        Healthy
```

Initially make this observational.

Do not immediately allow destructive container operations from the web interface.

Later, carefully consider:

- restart
- start
- stop

These actions must require appropriate authorization.

---

## Phase 9 — Notifications

Create notifications based on meaningful conditions.

Examples:

```text
Backup hasn't completed in 24 hours

Storage > 90%

Service offline

Ark unexpectedly restarted

Tailscale device joined
```

Possible notification channels later:

- Ark Cloud UI
- email
- mobile push
- Discord webhook

Start with internal notifications.

---

## Phase 10 — Notes / Personal Data

Add small useful personal-cloud features only where they naturally fit.

Potential examples:

- notes
- bookmarks
- snippets
- saved links

Do not turn Ark Cloud into a random collection of unrelated applications.

Every feature should support the concept of a personal cloud control plane.

---

## Phase 11 — Mobile-Friendly UI / PWA

Make Ark Cloud highly usable from an iPhone through Tailscale.

Possible PWA functionality:

- installable interface
- responsive layout
- offline shell
- notifications later

Do not build a native mobile application unless there is a strong reason.

---

## Phase 12 — Hardening

Before considering Ark Cloud mature:

- security review
- threat modeling
- least privilege
- rate limiting
- secure cookies
- CSRF protection where applicable
- XSS protections
- strict CORS configuration
- secret rotation
- dependency auditing
- structured logging
- backup validation
- recovery documentation
- database migrations
- integration tests
- health checks
- graceful shutdown
- monitoring
- audit events

---

# 9. Dashboard Vision

Eventually the primary interface might resemble:

```text
ARK CLOUD

System

Ark
● Online

CPU        12%
Memory     8.2 / 32 GB
Storage    862 GB / 2 TB
Uptime     4d 13h


Services

Tailscale       Healthy
Photos          Healthy
Files           Healthy
Vault           Healthy
Backups         Healthy


Devices

Ark             ● Online
Windows-PC      ● Online
iPhone          ● Online
Laptop          ○ Offline


Recent Activity

14:21  Laptop joined tailnet
14:03  16 photos uploaded
13:40  Backup completed
12:11  Service restarted
```

Do not attempt to build this complete interface during Phase 0.

Use it as architectural direction.

---

# 10. Authentication

Version 0.2 implements a deliberately narrow local username/password session boundary with Argon2id
password verification, HttpOnly SameSite session cookies, CSRF protection for mutations, and
logout. It is sufficient for the single local operator but is not a multi-user authorization
system.

Tailscale is a network security boundary, not a replacement for application authentication.

Potential future options:

- local username/password authentication
- passkeys/WebAuthn
- OAuth/OIDC
- Tailscale identity integration

Future authentication work requires a dedicated design review. Preserve the existing local-session
security properties, never log credentials, and consider MFA/passkeys only when there is a concrete
multi-user requirement.

---

# 11. Security Principles

This project will eventually handle sensitive personal information.

Security should therefore influence architecture from the beginning.

Follow:

- least privilege
- defense in depth
- secure defaults
- explicit trust boundaries
- input validation
- secrets outside source control
- dependency auditing
- minimal public exposure

Never commit:

- passwords
- API keys
- Tailscale credentials
- access tokens
- private SSH keys
- database passwords

Use:

```text
.env
```

locally when appropriate and provide:

```text
.env.example
```

with placeholder values.

Ensure `.env` is ignored by Git.

Do not create custom cryptographic algorithms.

---

# 12. Networking Philosophy

Ark Cloud is intended primarily for private access through Tailscale.

Preferred topology:

```text
Client
   ↓
Tailscale
   ↓
Ark
   ↓
Ark Cloud
```

Do not expose Ark Cloud publicly during initial development.

Services should avoid binding unnecessarily to every network interface.

Explain any port mappings created.

Keep internal services such as PostgreSQL inaccessible from outside the container network unless development explicitly requires otherwise.

---

# 13. Database Design

Use PostgreSQL.

Initially only introduce tables genuinely required by the system.

Likely eventual concepts include:

```text
users
integrations
events
notifications
files
settings
```

Do not create the entire eventual schema today.

Use proper migrations from the beginning.

Choose an appropriate Python ORM/database layer.

Keep domain models separate enough that integration-specific APIs do not dictate our database schema.

---

# 14. API Design

Backend endpoints should be versioned or structured cleanly.

Possible eventual structure:

```text
/api/health

/api/system
/api/system/metrics

/api/integrations
/api/integrations/{id}

/api/tailscale/devices

/api/files

/api/activity

/api/search

/api/notifications
```

Use Pydantic models.

Generate/use FastAPI's OpenAPI documentation.

Keep request/response schemas explicit.

Avoid sending raw third-party API responses directly to the frontend.

Normalize them first.

---

# 15. Observability

Ark Cloud itself should be observable.

Initially:

- structured application logs
- readable errors
- health endpoint

Later:

- metrics
- request IDs
- service health checks
- dashboards
- tracing if justified

Do not deploy a giant observability stack during Phase 0.

---

# 16. Testing

Testing should exist from the beginning.

Initial backend tests should cover things like:

- health endpoint
- configuration loading
- database connection or repository layer

Frontend should have appropriate basic testing where useful.

Later testing should include:

- unit tests
- integration tests
- API tests
- security-sensitive tests
- connector mocks

Third-party APIs such as Tailscale must be mockable.

Tests should not require contacting real production services.

---

# 17. Documentation

Documentation is part of the project.

Maintain:

```text
README.md

docs/
    architecture.md
    roadmap.md
    development.md
    security.md
```

Add more documents only when warranted.

Architecture documentation should explain WHY decisions were made.

Use lightweight Architecture Decision Records later if major architectural decisions accumulate.

---

# 18. Developer Experience

I should be able to clone the repository and understand how to run it.

Aim for:

```bash
git clone ...
cd ark-cloud
cp .env.example .env
docker compose up
```

or an equally clean workflow.

Avoid requiring a dozen manually installed host dependencies.

Use containerization where it improves reproducibility.

However, do not containerize things merely for appearance.

---

# 19. Coding Standards

Prioritize:

- readability
- maintainability
- explicitness
- type safety
- modularity
- clear naming

Avoid:

- giant files
- premature abstractions
- magic behavior
- unnecessary microservices
- excessive dependencies
- clever code that is difficult to understand

Ark Cloud should begin as a **modular monolith**.

Do NOT begin with microservices.

We can extract services later if there is an actual reason.

---

# 20. Git Practices

Use clean Git history.

Prefer commits representing meaningful units of work.

Examples:

```text
chore: initialize Ark Cloud monorepo

feat(api): add health endpoint

feat(web): add system status page

chore: add PostgreSQL development service

docs: document local development architecture
```

Do not create enormous commits containing unrelated changes.

Never commit secrets.

---

# 21. UI Direction

The UI should eventually feel similar to a modern infrastructure/cloud dashboard.

Design goals:

- clean
- dark-mode friendly
- information dense without being cluttered
- responsive
- fast
- accessible
- professional

Potential navigation:

```text
Overview

Files
Photos
Vault

Devices
Network
Services
Backups

Activity
Search

Settings
```

During Phase 0, keep UI extremely minimal.

Do not spend large amounts of time polishing visual design before the system architecture works.

---

# 22. Important Non-Goals

For now, DO NOT:

- implement our own password encryption
- recreate Immich
- recreate Tailscale
- expose Ark publicly
- create Kubernetes infrastructure
- create microservices
- deploy Kafka
- deploy Elasticsearch
- deploy Redis without a use case
- build a native iOS application
- create a complex plugin marketplace
- introduce distributed systems unnecessarily
- implement destructive infrastructure controls
- build every roadmap phase simultaneously

The project should become sophisticated because its requirements demand sophistication, not because technologies look impressive on a résumé.

---

# 23. Resume / Portfolio Goal

Ark Cloud should eventually demonstrate skills relevant to:

- Platform Engineering
- Infrastructure Engineering
- Site Reliability Engineering
- Backend Engineering
- Systems Engineering
- DevOps
- Cloud Engineering

Potential concepts demonstrated naturally:

- Linux administration
- networking
- secure private networking
- REST APIs
- third-party integrations
- PostgreSQL
- containerization
- service health monitoring
- observability
- authentication
- storage
- backups
- API abstraction
- frontend/backend architecture
- system design
- deployment
- security
- CI/CD

Do not add technologies solely so they can appear on this list.

---

# 24. Your Immediate Assignment

DO NOT build the complete roadmap.

Your current task is **Phase 0 only**.

Start by inspecting the current working directory and determining whether a repository already exists.

Then:

1. Propose the concrete Phase 0 architecture.

2. Explain any major decisions briefly.

3. Establish the repository structure.

4. Initialize the frontend.

5. Initialize the backend.

6. Add PostgreSQL.

7. Add Docker Compose development configuration.

8. Establish environment configuration.

9. Implement:

```text
GET /health
```

The response should provide meaningful information such as:

```json
{
  "status": "healthy",
  "service": "ark-cloud-api",
  "database": "connected"
}
```

10. Make the frontend call the backend and display basic health information.

11. Add appropriate linting and formatting.

12. Add initial backend tests.

13. Add `.gitignore`.

14. Add `.env.example`.

15. Write:

```text
README.md
docs/architecture.md
docs/roadmap.md
docs/development.md
docs/security.md
```

16. Verify the complete development environment actually starts.

17. Run tests.

18. Fix any problems discovered.

19. Review the resulting repository for unnecessary complexity.

20. Leave the project in a clean state ready for Phase 1.

---

# 25. Verification Requirement

Do not assume your implementation works.

Actually verify:

- containers start
- backend boots
- PostgreSQL boots
- backend connects to PostgreSQL
- `/health` responds correctly
- frontend starts
- frontend can contact backend
- tests pass
- linting passes
- no obvious secrets are tracked
- documentation commands match the actual implementation

If something cannot be verified in the available environment, explicitly document what remains unverified.

---

# 26. Dependency Rule

Before selecting frameworks, libraries, container images, or configuration syntax whose current recommended usage may have changed, verify the current official documentation.

Prefer:

- current stable releases
- officially maintained libraries
- well-supported packages

Avoid blindly using outdated tutorials.

Pin versions where reproducibility or compatibility warrants it.

---

# 27. Agent Behavior

You are authorized to:

- inspect the repository
- create files
- modify files
- initialize projects
- install project dependencies
- run development commands
- run containers
- run tests
- run linters
- troubleshoot errors
- refactor code you create
- create documentation

Do not stop after merely generating code.

Use an iterative workflow:

```text
inspect
→ design
→ implement
→ run
→ test
→ diagnose
→ fix
→ verify
→ document
```

Take ownership of solving ordinary implementation problems.

Do not ask me questions for trivial technical decisions you can reasonably make yourself.

If multiple reasonable options exist, select the simplest sound option and document the choice.

Ask me before:

- deleting important existing data
- modifying unrelated existing projects
- changing system-wide security configuration
- opening router/firewall exposure
- installing invasive system-level services
- performing irreversible actions
- handling real production secrets

---

# 28. Mentoring Requirement

Remember that I am using this project to learn.

As you work, periodically explain major concepts such as:

- why the frontend and API are separated
- what Docker networking is doing
- why PostgreSQL does not need a publicly exposed port
- how frontend requests reach the API
- what environment variables are doing
- what a health check is
- how an integration abstraction will work
- how containers discover each other
- why migrations matter

Keep these explanations concise and tied to actual work being performed.

When using unfamiliar command-line flags, explain the important flags.

Do not turn every action into a lecture.

---

# 29. Architectural Principle to Preserve

Always keep this mental model:

```text
                    Ark Cloud

                       │
              Unified abstraction
                       │

        ┌──────────────┼──────────────┐

     System         Tailscale        Storage
   Integration     Integration     Integration

        │               │               │
      Linux         Tailscale API      Files
```

Later:

```text
        ImmichIntegration
        VaultIntegration
        BackupIntegration
        ContainerIntegration
```

Ark Cloud consumes normalized information.

The rest of the application should not need intimate knowledge of every external service's implementation.

---

# 30. Long-Term Success Criterion

A successful Ark Cloud project eventually means I can connect to my private Tailscale network, open one application, and answer questions like:

```text
Is Ark healthy?

How much storage do I have left?

When was my last backup?

Which of my devices are online?

Are all of my services running?

What photos were recently uploaded?

Where is a particular file?

Is my password vault healthy?

What changed while I was away?
```

while keeping the infrastructure private, secure, maintainable, and understandable.

---

# Begin

Begin with Phase 0.

First inspect the environment and repository.

Before making substantial architectural decisions, briefly state the Phase 0 architecture you intend to implement and why.

Then proceed autonomously through implementation and verification.

Do not begin Phase 1 during this run unless Phase 0 is fully complete and I explicitly request continuation.
