# ISUP 5.0 bridge: Hikvision ISUP SDK (Linux x64) + ffmpeg (copy, no transcoding).
# sdk/ and inc/ are not in the repository (Hikvision licence): put them in
# before building, see README.md.
FROM ubuntu:22.04 AS build
RUN apt-get update && apt-get install -y --no-install-recommends g++ && rm -rf /var/lib/apt/lists/*
COPY inc/ /src/inc/
COPY sdk/ /opt/isup/lib/
COPY bridge.cpp /src/
RUN test -f /opt/isup/lib/libHCISUPCMS.so || { echo "isup/sdk/ is empty: add the Hikvision ISUP SDK libraries (isup/README.md)"; exit 1; }
RUN g++ -O2 -std=c++17 -Wall -I/src/inc /src/bridge.cpp -o /src/isup-bridge \
    -L/opt/isup/lib -lHCISUPCMS -lHCISUPStream -lhpr -lHCNetUtils -lpthread \
    -Wl,-rpath,/opt/isup/lib

FROM ubuntu:22.04
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*
COPY sdk/ /opt/isup/lib/
COPY --from=build /src/isup-bridge /opt/isup/lib/isup-bridge
ENV LD_LIBRARY_PATH=/opt/isup/lib:/opt/isup/lib/HCAapSDKCom
WORKDIR /opt/isup/lib
# Not root: the bridge parses data from the internet.
RUN useradd -r -u 10001 -d /opt/isup isup && mkdir -p /opt/isup/logs && chown -R isup /opt/isup/logs
USER isup
EXPOSE 17660/tcp 17660/udp 17661/tcp 8091/tcp
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD curl -fsS -m 2 http://localhost:8091/health || exit 1
CMD ["/opt/isup/lib/isup-bridge"]
