# Troubleshooting Scenarios

This project intentionally includes failure scenarios to practice structured DevOps troubleshooting.

The investigation workflow used throughout the project is:

```text
Symptom
   ↓
Hypothesis
   ↓
Evidence
   ↓
Narrow the Scope
   ↓
Root Cause
   ↓
Fix
   ↓
Verify
```

The goal is to avoid random configuration changes and instead isolate failures using observable evidence.

## 1. PostgreSQL Credential Mismatch

### Symptom

Nginx returned:

```text
502 Bad Gateway
```

FastAPI repeatedly failed during startup.

Application logs contained:

```text
password authentication failed for user "taskuser"
```

PostgreSQL logs confirmed the same authentication failure.

### Root Cause

The PostgreSQL password was changed in `.env`, but the existing PostgreSQL named volume already contained a database initialized with the previous password.

Recreating the PostgreSQL container changed its runtime environment but did not change the password stored in the persistent database state.

PostgreSQL reported:

```text
PostgreSQL Database directory appears to contain a database;
Skipping initialization
```

### Lesson

```text
Runtime configuration
≠
Persistent database state
```

Changing `POSTGRES_PASSWORD` does not automatically modify credentials inside an already initialized PostgreSQL database.

### Fix

Restore the matching credential or perform a controlled PostgreSQL password rotation.

Deleting the database volume would also reinitialize PostgreSQL, but would destroy persistent data and is not an acceptable production fix.

---

## 2. Wrong Docker Service Name

### Symptom

The application could not connect to PostgreSQL.

`DB_HOST` had been changed from:

```text
db
```

to:

```text
database
```

### Evidence

The valid service name resolved:

```bash
getent hosts db
```

The invalid service name did not:

```bash
getent hosts database
```

### Root Cause

Docker DNS was working correctly.

The application was requesting a hostname that did not exist on the Docker network.

### Lesson

```text
DNS lookup failure
```

does not necessarily mean:

```text
DNS infrastructure failure
```

The DNS service can be working correctly while the requested hostname is wrong.

### Fix

Restore:

```text
DB_HOST=db
```

and recreate the application container so it receives the correct runtime environment.

---

## 3. PostgreSQL Dependency Outage

### Symptom

PostgreSQL was intentionally stopped:

```bash
docker compose stop db
```

FastAPI remained alive:

```text
/health/live → 200
```

but became unavailable for normal operation:

```text
/health/ready → 503
```

The readiness response showed:

```json
{
  "postgresql": false,
  "redis": true
}
```

### Root Cause

The PostgreSQL dependency was unavailable while the FastAPI process itself remained running.

### Lesson

```text
Liveness
≠
Readiness
```

The application process can be alive while the service is not ready to handle real requests.

The incident also demonstrated:

```text
running
≠
healthy
```

The FastAPI container remained running but Docker marked it unhealthy.

### Fix

Start PostgreSQL:

```bash
docker compose start db
```

Then verify DNS resolution, readiness, health state, and application requests.

---

## 4. Wrong Application Bind Address

### Symptom

FastAPI was running, but Nginx could not connect to:

```text
app:8000
```

The application had been started with:

```text
--host 127.0.0.1
```

### Root Cause

Uvicorn was listening only on the loopback interface inside the application container.

The application container itself could reach:

```text
127.0.0.1:8000
```

but another container could not access the service through the Docker network interface.

### Lesson

Inside a container:

```text
127.0.0.1
```

means:

```text
this container only
```

For container-to-container access, the server must listen on an appropriate network interface such as:

```text
0.0.0.0
```

### Fix

Restore:

```text
--host 0.0.0.0
```

rebuild the application image, and recreate the container.

---

## 5. Host Port Conflict

### Symptom

Nginx could not start.

Docker returned:

```text
Bind for 127.0.0.1:8080 failed:
port is already allocated
```

### Root Cause

Another container had already published the same host socket:

```text
127.0.0.1:8080
```

### Lesson

The conflict occurs on the host port, regardless of which internal container port is being mapped.

```text
Host IP + Host Port
```

must be available before Docker can publish the service.

### Fix

Stop or remove the conflicting service, then start the project Nginx container again.

---

## 6. Broken Docker Health Check

### Symptom

The FastAPI container showed:

```text
running + unhealthy
```

while the real application readiness endpoint still returned HTTP 200.

### Root Cause

The Docker health check was intentionally configured to query a non-existent endpoint.

The application was healthy, but the monitoring command was wrong.

### Lesson

An unhealthy status does not automatically prove that the application itself is broken.

Always distinguish between:

```text
service failure
```

and:

```text
health-check failure
```

A Docker restart policy does not automatically restart a container simply because its health state becomes unhealthy while its main process is still running.

### Fix

Restore the correct health-check endpoint and recreate the application container.

---

## 7. Nginx Runtime Network-State Drift

This incident occurred naturally during the project rather than through deliberate fault injection.

### Symptom

Nginx repeatedly restarted.

Logs showed:

```text
host not found in upstream "app:8000"
```

FastAPI, PostgreSQL, and Redis were all healthy.

### Evidence

The application service existed:

```bash
docker compose config --services
```

and included:

```text
app
```

However, inspecting the frontend Docker network showed only the FastAPI container:

```text
frontend_network
      |
     app

nginx X
```

Nginx was not attached to the network it needed in order to resolve `app`.

### Root Cause

The actual runtime network membership of the existing Nginx container did not match the desired state defined by Docker Compose.

```text
Desired State:
nginx ∈ frontend_network

Actual State:
nginx ∉ frontend_network
```

The original cause of the runtime drift could not be proven from the available evidence, so no unsupported assumption was made.

### Fix

Recreate Nginx using the Compose desired state:

```bash
docker compose up -d --force-recreate nginx
```

After recreation, both Nginx and FastAPI were attached to the frontend network and Docker DNS could resolve the `app` service again.

### Lesson

```text
restart
```

and:

```text
recreate
```

are different operations.

Restarting starts the existing container again.

Recreating builds a new container instance from the current Compose configuration.

This incident also demonstrated the important operational distinction:

```text
Compose file
=
Desired State

Docker runtime
=
Actual State
```

When those states drift apart, runtime inspection is necessary.
