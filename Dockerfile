FROM python:3.10.16-alpine3.21 AS citra-builder

RUN apk update && apk add --no-cache \
    build-base \
    clang \
    clang-extra-tools \
    cmake \
    git \
    jack \
    openssl-dev \
    libx11-dev \
    libxext-dev \
    xorg-server-dev

WORKDIR /src
RUN git clone --recursive https://github.com/dylanpdx/citra.git .

RUN mkdir build && \
    cd build && \
    cmake ../ \
      -DSDL_RENDER=ON \
      -DENABLE_TESTS=OFF \
      -DENABLE_DEDICATED_ROOM=OFF \
      -DENABLE_QT=OFF \
      -DENABLE_WEB_SERVICE=OFF \
      -DENABLE_OPENAL=OFF \
      -DENABLE_OPENGL=OFF \
      -DENABLE_VULKAN=OFF \
      -DENABLE_LIBUSB=OFF \
      -DCITRA_ENABLE_BUNDLE_TARGET=OFF \
      -DENABLE_LTO=OFF \
      -DCITRA_WARNINGS_AS_ERRORS=OFF && \
    cmake --build . -- -j$(nproc)

FROM python:3.10.16-alpine3.21

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

RUN apk update && apk add --no-cache \
    build-base \
    ffmpeg \
    libffi-dev \
    libx11 \
    libxext \
    libxi \
    libxrandr \
    libsodium \
    libsodium-dev \
    libstdc++ \
    opus \
    sdl2

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt --break-system-packages

COPY api /app/api
COPY ttsmodachi_bot /app/ttsmodachi_bot
COPY --from=citra-builder /src/build/bin/Release /usr/local/bin

RUN mkdir -p /config /cache /data /opt
COPY api/sdl2-config.ini /config/sdl2-config.ini

CMD ["python", "-m", "ttsmodachi_bot.discord_bot"]
