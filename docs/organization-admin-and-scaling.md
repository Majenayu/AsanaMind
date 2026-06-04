# Organization Admin and Scaling Guide

This guide covers two practical topics for deploying AsanMinds to institutions:

- How sub-admins can create and track student groups through batches.
- How to scale the same codebase across multiple organizations without data clashes.

## 1. Creating and Managing Groups Through Batches

Sub-admins do not need a code change to create groups such as `2023`, `2024`, `2025`, or `2027`. The organization admin panel (`org.html`) already supports dynamic batch configuration.

### Steps for a Sub-Admin

1. Open the sub-admin panel.
2. Go to the `Config` tab.
3. In the `Batches` field, enter the batch years as a comma-separated list:

   ```text
   2023, 2024, 2025, 2027
   ```

4. Click `Save changes`.

After saving, those batches become available immediately across the organization workspace.

### Where the Batches Appear

- `Invite Student` tab: sub-admins can select the batch when inviting one student.
- `Edit Student` modal: sub-admins can move an existing student to another configured batch.
- Excel bulk import: the downloadable roster template uses the configured batches for its dropdown validation.
- `Students` tab: sub-admins can filter the student table by batch.

### Tracking and Bulk Operations

In the `Students` tab, sub-admins can filter by a specific batch, then select students and perform bulk actions such as:

- Move to batch, branch, or section.
- Reset progress.
- Send push notifications to selected students.
- Mark payment status.
- Delete selected students.

This makes the batch field the current group/cohort tracking mechanism for each organization.

## 2. Multi-Organization Architecture Options

AsanMinds can scale to multiple institutions in two main ways.

### Model A: Single Codebase, Multi-Instance Deployments

This is the recommended model for the current sales and deployment stage.

#### How It Works

Every client gets:

- The same application codebase.
- Its own Render Web Service.
- Its own MongoDB database name, cluster, or Atlas project.
- Its own environment variables.
- Optionally, its own custom domain.

Example:

```text
College X -> Render service X -> MongoDB database collegex_db
College Y -> Render service Y -> MongoDB database collegey_db
```

#### Pros

- Complete data isolation between institutions.
- Strong privacy story for colleges and enterprise buyers.
- No accidental database clashes when one client imports, edits, or deletes students.
- Easier custom domains such as `yoga.collegex.edu`.
- Isolated scaling, because a heavy client does not slow down every other client.
- Safer experiments and branding changes for one organization at a time.

#### Cons

- Higher hosting overhead because each institution has its own Render service.
- More deployment work when updating several clients.
- Environment variables must be managed carefully for every instance.
- Operational monitoring is split across services.

#### Best Fit

Use this model when institutions expect strong isolation, custom branding, custom domains, or independent contracts. It is especially appropriate while selling the product to colleges, because it is simple to explain and minimizes cross-organization risk.

### Model B: Single Codebase, Shared Database SaaS

This is a more centralized SaaS model.

#### How It Works

All clients share:

- One Render Web Service.
- One MongoDB cluster.
- One application runtime.

Organizations are separated by tenant fields, usually `organizationEmail` or a future `organizationId`, and every query must include the correct organization scope.

Example:

```text
College X students -> organizationId = collegex
College Y students -> organizationId = collegey
```

#### Pros

- Lower hosting cost.
- One deployment updates every organization.
- Easier centralized analytics and monitoring.
- Simpler to run as a classic self-serve SaaS product.

#### Cons

- Data isolation depends on correct query scoping everywhere.
- A missed `organizationEmail` filter can expose or modify another organization's data.
- More complex authorization, indexing, testing, and auditing.
- Harder to support separate custom OAuth apps, custom domains, and institution-specific settings.
- One production incident can affect every client.

#### Best Fit

Use this model after the platform has stronger tenant-level controls, automated tests around organization scoping, clear audit logs, and a product requirement for centralized SaaS operations.

## 3. Environment Variables Per Render Instance

For the multi-instance model, each Render Web Service should have its own environment variable values.

### `MONGO_URI`

Each institution should point to a distinct database or cluster.

```text
College X: mongodb+srv://USER:PASSWORD@CLUSTER.mongodb.net/collegex_db?retryWrites=true&w=majority
College Y: mongodb+srv://USER:PASSWORD@CLUSTER.mongodb.net/collegey_db?retryWrites=true&w=majority
```

This is the most important protection against data clashes.

### `GOOGLE_CLIENT_ID`

Each institution should ideally have its own Google Cloud OAuth application.

Benefits:

- The consent screen can show the correct institution or product branding.
- OAuth redirect URLs can be scoped to that institution's Render URL or custom domain.
- Future domain restrictions can be managed per college.

### `ADMIN_EMAILS`

Set this to only the super-admin emails allowed for that specific deployment.

```text
ADMIN_EMAILS=admin@collegex.edu,owner@asanminds.com
```

Do not reuse a broad admin list across every client unless those people truly need access to every deployment.

### `ADMIN_PASSWORD`

Use a unique admin password per deployment. This protects the admin panel even if an email address is accidentally included in `ADMIN_EMAILS`.

### `SECRET_KEY`

Generate a unique secret key for every Render app.

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

This prevents signed Flask session cookies from being shared or trusted across deployments.

### Other Client-Specific Variables

Consider setting these separately when needed:

- `SENDGRID_FROM_EMAIL`
- `SENDGRID_API_KEY`
- `VAPID_PUBLIC_KEY`
- `VAPID_PRIVATE_KEY`
- Any future branding, domain, or feature-flag variables

## 4. Preventing Data Clashes

### For the Recommended Multi-Instance Model

Use this deployment checklist for every new organization:

1. Create a new Render Web Service from the same repository.
2. Set a unique `MONGO_URI` database name or cluster.
3. Set a unique `SECRET_KEY`.
4. Configure a client-specific `GOOGLE_CLIENT_ID`.
5. Set only the correct `ADMIN_EMAILS`.
6. Add the organization's admin through the super-admin or invitation flow.
7. In the sub-admin panel, configure batches, branches, and sections before importing students.
8. Import students only through that organization's deployment URL.

With this setup, one college cannot accidentally read, update, reset, or delete another college's students because they are stored in separate databases.

### For a Future Shared SaaS Model

If the product later moves to one shared SaaS deployment, add stricter tenant guarantees before launch:

- Use a stable `organizationId` instead of email as the primary tenant key.
- Require every student, invitation, certificate, progress record, push subscription, and audit entry to carry the tenant key.
- Add compound indexes such as `{ organizationId: 1, email: 1 }`.
- Centralize tenant-scoped query helpers and avoid raw unscoped queries in routes.
- Add automated tests that attempt cross-organization access and confirm it fails.
- Log admin actions with actor email, organization ID, target email, action, and timestamp.

## 5. Sub-Admin and Admin Isolation

The current app already scopes many organization admin operations by `organizationEmail`. In the multi-instance model, isolation is even stronger because each deployment also has its own database.

For separate institutional deployments, the sub-admin experience can be kept simple:

- Sub-admins should only see their organization's students.
- They should not need to manually filter by `organizationEmail`.
- Organization-specific settings such as batches, branches, sections, limits, and branding should be loaded from that deployment's own database.

This gives each client a clean admin experience while keeping the product codebase shared.

## 6. Recommended Scaling Path

Start with Model A: single codebase, multi-instance deployments.

This gives AsanMinds the best near-term balance of security, sales clarity, and operational simplicity for institutions. Keep the codebase tenant-aware internally, but sell and deploy each college as a separate isolated instance until there is a strong business reason to consolidate into a shared SaaS model.
