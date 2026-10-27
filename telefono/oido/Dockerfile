# El oído de Jarvis (servidor.py) con whisper.cpp por Vulkan, para la RX 580 de jacobo.
# Las versiones van fijadas a las que se midieron el 2026-10-27 («Whisper medido en
# jacobo», telefono/PARCHES.md). Se construye EN jacobo: GGML_NATIVE compila para su CPU.

FROM ubuntu:24.04 AS construccion
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake git ca-certificates libvulkan-dev glslc \
    && rm -rf /var/lib/apt/lists/*
# Las SPIRV-Headers de Ubuntu son más viejas de lo que pide ggml-vulkan; estas son las que
# compilaron en jacobo
ARG SPIRV_HEADERS=fbf86836a9b1966586faf7be7bb8a6440e156d62
ARG WHISPER_CPP=231638a0717b7822784297e5980965ffcec05810
RUN git init -q /spirv && cd /spirv \
    && git fetch -q --depth 1 https://github.com/KhronosGroup/SPIRV-Headers.git $SPIRV_HEADERS \
    && git checkout -q FETCH_HEAD \
    && cmake -S . -B build -DCMAKE_INSTALL_PREFIX=/usr/local >/dev/null && cmake --install build >/dev/null
RUN git init -q /src && cd /src \
    && git fetch -q --depth 1 https://github.com/ggml-org/whisper.cpp.git $WHISPER_CPP \
    && git checkout -q FETCH_HEAD \
    && cmake -S . -B build -DGGML_VULKAN=1 -DGGML_CCACHE=OFF -DBUILD_SHARED_LIBS=OFF \
         -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS="-I/usr/local/include" \
    && cmake --build build -j"$(nproc)" --target whisper-server

FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends \
      mesa-vulkan-drivers libvulkan1 libgomp1 ffmpeg python3 python3-aiohttp \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir /cache && chown 1000:1000 /cache
COPY --from=construccion /src/build/bin/whisper-server /opt/whisper/whisper-server
COPY acuerdo.py servidor.py /app/
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MESA_SHADER_CACHE_DIR=/cache HOME=/tmp
EXPOSE 8770
CMD ["python3", "servidor.py"]
