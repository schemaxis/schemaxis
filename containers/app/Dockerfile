# Definitions only: input bundles and native acceptance remain required.
# Build context is containers/; the trusted builder supplies artifacts/.
FROM --platform=linux/amd64 python:3.14.4-slim-trixie@sha256:2409290aa375de35f6492db84c700067d5c4c2aacfaf770c155d7528fb68bcf1 AS assemble
ARG RUNTIME_SHA256
ARG WHEEL_SHA256
ARG RUNTIME_FAMILY
ARG RUNTIME_VERSION
ENV RUNTIME_FAMILY=$RUNTIME_FAMILY RUNTIME_VERSION=$RUNTIME_VERSION
COPY common/assemble.py /assemble.py
COPY artifacts/runtime.tar /inputs/runtime.tar
COPY artifacts/schemaxis.whl /inputs/schemaxis.whl
RUN RUNTIME_SHA256="$RUNTIME_SHA256" WHEEL_SHA256="$WHEEL_SHA256" python3 -I -B /assemble.py

FROM --platform=linux/amd64 python:3.14.4-slim-trixie@sha256:2409290aa375de35f6492db84c700067d5c4c2aacfaf770c155d7528fb68bcf1
ARG RUNTIME_FAMILY
ARG RUNTIME_VERSION
LABEL org.opencontainers.image.title="Schemaxis application worker" \
      io.schemaxis.runtime.family="$RUNTIME_FAMILY" \
      io.schemaxis.runtime.version="$RUNTIME_VERSION" \
      io.schemaxis.qualification="pending"
COPY --from=assemble /assembled/runtime /opt/runtime
COPY --from=assemble /assembled/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=assemble /assembled/config /opt/schemaxis
COPY common/strip_managers.py /strip_managers.py
RUN python3 -I -B /strip_managers.py && rm /strip_managers.py \
    && mkdir -p /job && chown 10001:10001 /job \
    && chmod -R go-w /opt/runtime /opt/schemaxis /usr/local/lib/python3.14/site-packages
ENV PATH="/opt/runtime/bin:/usr/local/bin:/usr/bin:/bin" \
    LD_LIBRARY_PATH="/opt/runtime/lib" \
    SCHEMAXIS_CONFIG="/opt/schemaxis/runtime.json" \
    HOME="/job" TMPDIR="/job" XDG_CACHE_HOME="/job/.cache" \
    PYTHONDONTWRITEBYTECODE="1" PYTHONUNBUFFERED="1" \
    OPENBLAS_NUM_THREADS="1" OMP_NUM_THREADS="1"
USER 10001:10001
WORKDIR /job
ENTRYPOINT ["python3", "-I", "-B", "-m", "schemaxis"]
CMD ["--help"]
