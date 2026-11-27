# The DrugWatch API's production image (Phase 12, ADR 0021: deployed to Render).
#
# Two stages: the first has the JDK and Maven and compiles the jar; the second starts from a
# plain JRE (no compiler, no Maven, no source code) and only copies the finished jar in. Render
# only knows how to run a container image - it has no JDK or Maven of its own, unlike this Mac.
#
# **Build context is the REPO ROOT**, hence the `backend/` prefixes below - so build it with
#   docker build -f backend/Dockerfile .
# and not from inside backend/. Render's Docker builds always use the repository root as the
# context: setting its "Root Directory" to `backend` changes where it runs commands but **not**
# the build context, so paths relative to backend/ failed there with `"/src": not found` while
# building fine on this Mac. Same shape as infra/ml-serving/Dockerfile.space, which needs the
# repo root anyway (it reaches into ../ml) and deploys to Render unchanged.

FROM eclipse-temurin:21-jdk-noble AS build
WORKDIR /app

# The wrapper and pom.xml first, before any source code: Docker only reruns a step when the
# files it COPYs change, so editing a .java file later skips re-downloading every dependency.
COPY backend/.mvn/ .mvn/
COPY backend/mvnw backend/pom.xml ./
RUN ./mvnw dependency:go-offline -B

COPY backend/src ./src
# -DskipTests: CI already ran the full suite (incl. Testcontainers) before this image is built;
# repeating it here would need Docker-in-Docker for no new information.
RUN ./mvnw clean package -DskipTests -B

# noble (Ubuntu 24.04), not jammy: this Mac already has the noble tag cached from another
# project, so the build needs no network for the base image at all on a slow link - and the two
# Ubuntu LTS releases make no difference to a Java app that only runs a JRE and curl.
FROM eclipse-temurin:21-jre-noble
# curl: the only thing the final image needs beyond the JRE, for the container healthcheck below.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# The jar's filename carries the Maven version (drugwatch-api-0.1.0.jar); the wildcard copies
# whatever that is today and renames it, so a version bump never needs a matching Dockerfile edit.
COPY --from=build /app/target/*.jar app.jar

# Non-root, same convention as infra/ml-serving/Dockerfile: this process needs no write access to
# anything, and Render runs the image on the open internet.
RUN useradd --create-home --uid 10001 api && chown -R api /app
USER api

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
  CMD curl -fsS http://localhost:8080/actuator/health || exit 1

# MaxRAMPercentage, not a fixed -Xmx: the container's own memory limit (Render: 512 MB) decides
# the heap at startup, so one image works on a laptop test with --memory=512m and on Render
# without editing a number by hand. 75% leaves headroom for thread stacks and JIT code, outside
# the heap, which -Xmx as "75% of RAM" would not.
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75.0", "-jar", "app.jar"]
