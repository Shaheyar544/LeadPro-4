FROM ghcr.io/jo-inc/camofox-browser:1.14.0@sha256:86c79eed8a6b3a78859f73bc70d6003c5566b85e969354ec454524b28197ffce
COPY camofox.config.json /app/camofox.config.json
RUN mkdir -p /home/node/.cache && mv /root/.cache/camoufox /home/node/.cache/camoufox && chown -R node:node /home/node/.cache
COPY harden.cjs /tmp/harden.cjs
RUN node /tmp/harden.cjs
USER node
