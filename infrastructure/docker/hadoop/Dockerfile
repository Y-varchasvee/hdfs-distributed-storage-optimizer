# Genuine Apache Hadoop built from the official Apache release tarball.
# The published apache/hadoop images are amd64-only, so this image picks the tarball
# matching the build architecture and verifies the published SHA-512 before use.
FROM eclipse-temurin:17-jre-jammy

ARG HADOOP_VERSION=3.5.0
ENV HADOOP_HOME=/opt/hadoop \
    HADOOP_CONF_DIR=/opt/hadoop/etc/hadoop \
    PATH=/opt/hadoop/bin:/opt/hadoop/sbin:$PATH

RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends curl procps >/dev/null \
 && rm -rf /var/lib/apt/lists/*

RUN set -eu; \
    case "$(uname -m)" in \
      aarch64|arm64) TARBALL="hadoop-${HADOOP_VERSION}-aarch64.tar.gz" ;; \
      x86_64)        TARBALL="hadoop-${HADOOP_VERSION}.tar.gz" ;; \
      *) echo "unsupported architecture $(uname -m)"; exit 1 ;; \
    esac; \
    BASE="https://downloads.apache.org/hadoop/common/hadoop-${HADOOP_VERSION}"; \
    curl -fsSL --retry 3 -o "/tmp/${TARBALL}" "${BASE}/${TARBALL}"; \
    curl -fsSL --retry 3 -o "/tmp/${TARBALL}.sha512" "${BASE}/${TARBALL}.sha512"; \
    EXPECTED="$(grep -oE '[0-9a-fA-F]{128}' "/tmp/${TARBALL}.sha512" | head -1 | tr 'A-F' 'a-f')"; \
    ACTUAL="$(sha512sum "/tmp/${TARBALL}" | cut -d' ' -f1)"; \
    [ "$EXPECTED" = "$ACTUAL" ] || { echo "SHA-512 mismatch for ${TARBALL}"; exit 1; }; \
    mkdir -p /opt && tar -xzf "/tmp/${TARBALL}" -C /opt; \
    mv "/opt/hadoop-${HADOOP_VERSION}" /opt/hadoop; \
    rm -f "/tmp/${TARBALL}" "/tmp/${TARBALL}.sha512"; \
    rm -rf /opt/hadoop/share/doc /opt/hadoop/share/hadoop/yarn /opt/hadoop/share/hadoop/mapreduce \
           /opt/hadoop/share/hadoop/tools

# YARN and MapReduce jars are removed to save space (only HDFS daemons run here), but
# Hadoop's launcher scripts still require these directories to exist.
RUN groupadd -r hadoop && useradd -r -g hadoop -d /opt/hadoop hadoop \
 && mkdir -p /opt/hadoop/share/hadoop/yarn /opt/hadoop/share/hadoop/mapreduce /opt/hadoop/share/hadoop/tools \
 && mkdir -p /data /opt/hadoop/logs && chown -R hadoop:hadoop /data /opt/hadoop

COPY entrypoint.sh /usr/local/bin/hadoop-entrypoint.sh
RUN chmod +x /usr/local/bin/hadoop-entrypoint.sh

USER hadoop
WORKDIR /opt/hadoop
ENTRYPOINT ["/usr/local/bin/hadoop-entrypoint.sh"]
