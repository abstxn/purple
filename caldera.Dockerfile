FROM python:3.12-slim AS builder

ARG CALDERA_VERSION=5.0.0

RUN apt-get update && apt-get install -y \
    git curl build-essential nodejs npm \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/mitre/caldera.git --recursive \
    --branch ${CALDERA_VERSION} --depth 1 /usr/src/app

WORKDIR /usr/src/app
RUN pip install --no-cache-dir -r requirements.txt

# Build the Vue frontend at image build time
WORKDIR /usr/src/app/plugins/magma
RUN npm install && npm run build

FROM python:3.12-slim
WORKDIR /usr/src/app
COPY --from=builder /usr/src/app .
COPY --from=builder /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=builder /usr/local/bin /usr/local/bin

EXPOSE 8888 7010 7011 8022
CMD ["python", "server.py", "--insecure"]