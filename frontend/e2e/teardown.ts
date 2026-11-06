/** Remove the HDFS directory used by the browser tests. */
export default async function teardown() {
  await fetch("http://127.0.0.1:9870/webhdfs/v1/hdfs-optimizer-e2e?op=DELETE&recursive=true&user.name=hadoop", { method: "DELETE" });
}
