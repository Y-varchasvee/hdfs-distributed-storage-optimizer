#!/usr/bin/env bash
# Renders Hadoop config from mounted templates and starts one HDFS daemon in the foreground.
set -euo pipefail
ROLE="${1:?usage: hadoop-entrypoint.sh namenode|datanode}"
: "${HDFS_REPLICATION:=3}"
: "${DATANODE_HOSTNAME:=$(hostname)}"

cp /templates/core-site.xml "$HADOOP_CONF_DIR/core-site.xml"
sed -e "s|@REPLICATION@|${HDFS_REPLICATION}|g" -e "s|@DATANODE_HOSTNAME@|${DATANODE_HOSTNAME}|g" \
    /templates/hdfs-site.xml > "$HADOOP_CONF_DIR/hdfs-site.xml"
: > "$HADOOP_CONF_DIR/workers"

case "$ROLE" in
  namenode)
    mkdir -p /data/nn
    # Format only an empty name directory, so a restart can never wipe existing metadata.
    if [ ! -f /data/nn/current/VERSION ]; then
      echo "[entrypoint] formatting empty NameNode directory"
      hdfs namenode -format -nonInteractive -force -clusterId "${HDFS_CLUSTER_ID:-hdfs-optimizer}"
    fi
    exec hdfs namenode
    ;;
  datanode)
    mkdir -p /data/dn
    exec hdfs datanode
    ;;
  *) exec "$@" ;;
esac
