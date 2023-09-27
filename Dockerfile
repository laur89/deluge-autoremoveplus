ARG PYTHON_VERSION
FROM python:${PYTHON_VERSION}-slim AS builder
WORKDIR /src
ADD . .
RUN ./setup.py bdist_egg

FROM scratch AS exporter
COPY --from=builder /src/dist/*.egg .
