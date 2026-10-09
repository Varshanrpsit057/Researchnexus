# Deploying ResearchNexus to AWS

The exact procedure, first deployment to routine releases. The architecture
and its cost are in [AWS_ARCHITECTURE.md](AWS_ARCHITECTURE.md); every setting
in [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md); sign-in and email in
[AUTHENTICATION.md](AUTHENTICATION.md); running it and rolling back in
[OPERATIONS_AND_ROLLBACK.md](OPERATIONS_AND_ROLLBACK.md).

Who does what is marked on every step:

- 🧑‍💻 **you, with AWS / DNS / GitHub access** -- creates resources (and cost) or needs an account owner's approval;
- 🤖 **the code** -- already in this repository (templates, images, pipeline), run by the command shown.

Nothing here has been run against a real AWS account by the code's authors:
no AWS resources exist until you create them. Each step says how to check it
worked.

## 0. Before you start 🧑‍💻

- An AWS account you may create resources in (an IAM identity with
  administrator rights for this setup), and the [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
  signed in to it (`aws sts get-caller-identity`).
- A domain you control, with an address for the app, e.g.
  `researchnexus.example.org` (and `staging.researchnexus.example.org`).
- Admin rights on the GitHub repository.
- Docker, to build the first images (afterwards GitHub Actions builds them).
- A region close to the users, e.g. `eu-west-1`, used everywhere below.

```bash
export AWS_REGION=eu-west-1
export ENV=staging                       # repeat sections 3-9 later with ENV=production
export DOMAIN=staging.researchnexus.example.org
export ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export REGISTRY=$ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com
```

## 1. Bootstrap: image repositories and the deploy role 🧑‍💻 (runs 🤖 `bootstrap.yml`)

Once per account and region:

```bash
aws cloudformation deploy --region $AWS_REGION \
  --stack-name researchnexus-bootstrap \
  --template-file infra/cloudformation/bootstrap.yml \
  --capabilities CAPABILITY_NAMED_IAM
# if the account already has GitHub's OIDC provider, add:
#   --parameter-overrides CreateGitHubOidcProvider=false ExistingGitHubOidcProviderArn=arn:aws:iam::<account>:oidc-provider/token.actions.githubusercontent.com
aws cloudformation describe-stacks --stack-name researchnexus-bootstrap --query "Stacks[0].Outputs" --output table
```

Check: the outputs list the two repository URIs and `DeployRoleArn`.

## 2. Email: Amazon SES 🧑‍💻

Follow **Setting up Amazon SES** in [AUTHENTICATION.md](AUTHENTICATION.md#setting-up-amazon-ses-one-time-needs-aws-and-dns-access):
verify the domain (DKIM, SPF, DMARC records in your DNS), request production
access (until granted, only verified recipient addresses get email), and
create SMTP credentials. Keep the SMTP username and password for step 4.

Check: SES console shows the domain as *Verified*; the account dashboard shows
*Production access* (or verify your own test address meanwhile).

## 3. TLS certificate 🧑‍💻

```bash
aws acm request-certificate --region $AWS_REGION --domain-name $DOMAIN --validation-method DNS
aws acm describe-certificate --region $AWS_REGION --certificate-arn <arn> \
  --query "Certificate.DomainValidationOptions[0].ResourceRecord"
```

Create that CNAME record in your DNS, then wait for `Status: ISSUED`
(`aws acm wait certificate-validated --certificate-arn <arn>`).

## 4. The app secret 🧑‍💻

One JSON secret per environment, generated on your machine and sent straight
to Secrets Manager (nothing is written to disk or shell history; paste the
SMTP values when prompted):

```bash
read -rsp "SES SMTP username: " SMTP_USER; echo
read -rsp "SES SMTP password: " SMTP_PASS; echo
aws secretsmanager create-secret --region $AWS_REGION \
  --name researchnexus/$ENV/app \
  --secret-string "$(SMTP_USER="$SMTP_USER" SMTP_PASS="$SMTP_PASS" python3 -c '
import json, os, secrets, base64
print(json.dumps({
  "SECRET_KEY": secrets.token_urlsafe(48),
  "KEY_VAULT_SECRET": base64.urlsafe_b64encode(os.urandom(32)).decode(),
  "SMTP_USERNAME": os.environ["SMTP_USER"],
  "SMTP_PASSWORD": os.environ["SMTP_PASS"],
}))')"
unset SMTP_USER SMTP_PASS
```

Optional keys in the same JSON: `OPENALEX_API_KEY`, `SEMANTIC_SCHOLAR_API_KEY`,
`CORE_API_KEY` (add them to the backend task definition's `Secrets` to use
them). **Never change `KEY_VAULT_SECRET` once people have saved keys** -- they
could no longer be decrypted.

Check: `aws secretsmanager describe-secret --secret-id researchnexus/$ENV/app` (shows no values).

## 5. The first images 🧑‍💻 (builds 🤖 `backend/Dockerfile`, `frontend/Dockerfile`)

Afterwards the pipeline does this; the very first images come from your machine:

```bash
export SHA=$(git rev-parse HEAD)
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $REGISTRY
docker build -t $REGISTRY/researchnexus/backend:$SHA ./backend
docker build --build-arg NEXT_PUBLIC_API_BASE_URL= -t $REGISTRY/researchnexus/frontend:$SHA ./frontend
docker push $REGISTRY/researchnexus/backend:$SHA
docker push $REGISTRY/researchnexus/frontend:$SHA
```

The frontend is built with an empty API address: it calls `/api` on its own
address, so one image serves every environment and contains no backend URL.

## 6. The application stack 🧑‍💻 (runs 🤖 `researchnexus.yml`)

Create it with **no backend containers** first, so nothing serves traffic
before the database is migrated (step 7):

```bash
aws cloudformation deploy --region $AWS_REGION \
  --stack-name researchnexus-$ENV \
  --template-file infra/cloudformation/researchnexus.yml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    EnvironmentName=$ENV \
    DomainName=$DOMAIN \
    CertificateArn=<certificate arn from step 3> \
    BackendImage=$REGISTRY/researchnexus/backend:$SHA \
    FrontendImage=$REGISTRY/researchnexus/frontend:$SHA \
    AppSecretArn=$(aws secretsmanager describe-secret --secret-id researchnexus/$ENV/app --query ARN --output text) \
    EmailFrom="ResearchNexus <no-reply@researchnexus.example.org>" \
    ContactEmail=ops@researchnexus.example.org \
    AlarmEmail=you@example.org \
    BackendDesiredCount=0
```

For production also pass `DbMultiAz=true DbBackupRetentionDays=14` (see the
cost table). Creating the database takes ~10 minutes.

Check: `aws cloudformation describe-stacks --stack-name researchnexus-$ENV --query "Stacks[0].StackStatus"`
is `CREATE_COMPLETE`; confirm the SNS alarm subscription email.

## 7. Migrate the database 🤖 (you run the command)

The backend image applies the migrations as a one-off task (`migrate` =
`alembic upgrade head`; additive, never drops data):

```bash
out() { aws cloudformation describe-stacks --stack-name researchnexus-$ENV --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
TASK=$(aws ecs run-task --cluster $(out ClusterName) --launch-type FARGATE \
  --task-definition researchnexus-$ENV-backend \
  --network-configuration "awsvpcConfiguration={subnets=[$(out BackendSubnets)],securityGroups=[$(out BackendSecurityGroup)],assignPublicIp=ENABLED}" \
  --overrides '{"containerOverrides":[{"name":"backend","command":["migrate"]}]}' \
  --query 'tasks[0].taskArn' --output text)
aws ecs wait tasks-stopped --cluster $(out ClusterName) --tasks $TASK
aws ecs describe-tasks --cluster $(out ClusterName) --tasks $TASK --query 'tasks[0].containers[0].exitCode'
```

Check: exit code `0`; the backend log group `/researchnexus/$ENV/backend`
shows `Running upgrade ... -> 0023`.

**Bringing existing data (optional).** To move a local SQLite database into
the new PostgreSQL instead of starting empty, see *Moving existing data* in
[OPERATIONS_AND_ROLLBACK.md](OPERATIONS_AND_ROLLBACK.md#moving-existing-data-into-postgresql).
Do it now, before step 8 (the copy refuses a database that already has rows).

## 8. Start the backend 🧑‍💻

```bash
# parameters not named keep their current values
aws cloudformation deploy --region $AWS_REGION --stack-name researchnexus-$ENV \
  --template-file infra/cloudformation/researchnexus.yml --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides BackendDesiredCount=1
```

(or in the CloudFormation console: *Update stack > Use current template*, change only `BackendDesiredCount` to `1`).

A container that can't start because of its configuration says why in its log:
`ResearchNexus can't start with this configuration:` followed by each missing
setting's name (never a value).

## 9. DNS 🧑‍💻

Point the app's address at the load balancer: a CNAME `$DOMAIN -> $(out LoadBalancerDnsName)`,
or a Route 53 alias record.

## 10. Verify 🧑‍💻 (checks the code makes possible)

```bash
curl -fsS https://$DOMAIN/health/live                 # {"status":"ok"}
curl -fsS https://$DOMAIN/health/ready                # status ok; checks: database, schema, storage all "ok"; environment = $ENV
curl -fsS https://$DOMAIN/health/providers | jq .     # email configured; the scholarly sources' last check
curl -fsS https://$DOMAIN/api/v1/auth/session         # {"user":null}
curl -s -o /dev/null -w "%{http_code}\n" https://$DOMAIN/api/v1/workspaces    # 401
curl -s -o /dev/null -w "%{http_code}\n" http://$DOMAIN/                      # 301 to https
curl -sI https://$DOMAIN/ | grep -i -E "strict-transport|content-security"    # both present
```

Then in a browser:

1. **Sign up** at `https://$DOMAIN/sign-up` with a real inbox. The code
   arrives (check spam once; if it never does, see *Troubleshooting* in
   OPERATIONS_AND_ROLLBACK.md). Enter it: you land on *Welcome, <name>*.
2. **Sign out**, then **sign in** again: password, then a new code.
3. **Forgot password** with the same email: code + new password signs you in.
4. Settings > Account lists this device; Settings > Language models: save a
   model key and run *Test*.
5. Upload a PDF, analyse it, run discovery, start a workspace, ask the chat a
   question, compare two papers and export the table to Word.
6. In the browser's developer tools, the `__Host-rn_session` cookie is
   `HttpOnly; Secure; SameSite=Lax`, and `document.cookie` doesn't show it.

## 11. Continuous deployment 🧑‍💻 (enables 🤖 `.github/workflows/deploy.yml`)

In the GitHub repository (Settings):

1. **Environments**: create `staging` and `production`. On `production`, add
   *Required reviewers* (and optionally restrict it to the `main` branch).
2. **Variables** (Settings > Secrets and variables > Actions > Variables):
   repository-level `AWS_REGION` and `AWS_DEPLOY_ROLE_ARN` (step 1's output);
   per environment `APP_DOMAIN` (`staging.researchnexus.example.org`,
   `researchnexus.example.org`). No AWS keys are stored: the workflow
   assumes the role by OIDC.
3. When staging is verified, set repository variable `AWS_DEPLOY_ENABLED` to `true`.

From then on:

- **Staging**: every push to `main` runs CI (lint, types, tests on SQLite and
  PostgreSQL, dependency audits, production build, image builds and a
  container smoke test); when it passes, *Deploy* builds and pushes the
  images, registers new task definitions, runs the migration task, rolls the
  services out, waits for them to be stable and smoke-tests the address. Any
  failure after the rollout puts the previous release back.
- **Production**: Actions > *Deploy* > *Run workflow*, environment
  `production`, and the commit SHA already running on staging. A reviewer
  approves; the same images (never rebuilt) go out the same way.

## 12. Production

Repeat steps 3-10 with `ENV=production` and the production domain (its own
certificate and its own secret: never share `SECRET_KEY` or
`KEY_VAULT_SECRET` between environments), `DbMultiAz=true`,
`DbBackupRetentionDays=14`. Then releases go through step 11.

## Rolling back

See [OPERATIONS_AND_ROLLBACK.md](OPERATIONS_AND_ROLLBACK.md#rolling-back). In short: re-run *Deploy* for
the previous SHA, or point each service at its previous task definition.
Migrations are additive, so the previous release runs against the newer
schema; the database is never rolled back by the pipeline.

## Local, production-like (no AWS)

`docker compose up --build` (after `cp .env.example .env` and filling in
`POSTGRES_PASSWORD`, `RESEARCHNEXUS_SECRET_KEY`, `RESEARCHNEXUS_KEY_VAULT_SECRET`)
runs the production images with PostgreSQL on http://localhost:3000 and
http://localhost:8000; sign-in codes appear in `docker compose logs -f backend`.
