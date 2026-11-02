FROM eu.gcr.io/ramadhan-s4g/eo-base:latest

WORKDIR /usr/src/app

RUN python3 -m venv .venv
ENV PATH=$PATH:/usr/src/app/.venv/bin

COPY src src
COPY README.md LICENSE pyproject.toml ./

# s4g-lib is private: the token is mounted only for this step and passed to git via env
RUN --mount=type=secret,id=github_token,required=true \
  GIT_CONFIG_COUNT=1 \
  GIT_CONFIG_KEY_0="url.https://x-access-token:$(cat /run/secrets/github_token)@github.com/.insteadOf" \
  GIT_CONFIG_VALUE_0="https://github.com/" \
  .venv/bin/pip install -e . --force-reinstall --no-cache-dir

COPY job job

ENV GS_NO_SIGN_REQUEST=YES
ENV AWS_NO_SIGN_REQUEST=YES
ENV GDAL_HTTP_MAX_RETRY=5
ENV GDAL_HTTP_RETRY_DELAY=5
ENV GDAL_HTTP_UNSAFE_RENEGOTIATION=YES
ENV VSI_CACHE=TRUE
ENV GDAL_HTTP_TCP_KEEPALIVE=YES
ENV GDAL_HTTP_UNSAFESSL=YES
