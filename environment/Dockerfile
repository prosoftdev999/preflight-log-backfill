FROM python:3.13-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641

# The sessions were driven by Playwright 1.63.0, which pins the headless Chromium build
# (153.0.8010.12). The same build is installed here. --with-deps runs apt-get itself.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
RUN pip install --no-cache-dir playwright==1.63.0 \
    && playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/* \
    && chmod -R a+rX /opt/pw-browsers

WORKDIR /app
COPY data/ /app/data/
RUN mkdir -p /app/output && chmod 0777 /app/output
