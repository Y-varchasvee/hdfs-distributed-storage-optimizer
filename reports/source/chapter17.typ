#import "lib.typ": *

#let I = results("I_before_after").rows
#let J = results("J_failure_handling")

= Conclusion

== What was built
This project built a working deduplication layer on an unmodified Apache Hadoop 3.5.0 cluster: a FastAPI backend, a relational metadata model, whole-file and fixed-size chunk deduplication through content-addressable storage, safe optimization, replication management, monitoring, a ten-page dashboard and reproducible experiments on authentic files.

== What was verified
#counts.unit.passed unit and API tests, #counts.integration.passed integration tests on the real cluster and #counts.browser.passed real-browser tests passed. Every restored file in every experiment matched its original SHA-256. Real DataNode, NameNode and process-kill failures caused no data loss, and an interrupted job resumed safely.

== Results achieved
Savings on exact duplicates matched theory exactly. On #I.at(0).files files comprising three copies of each of nine books, whole-file optimization reduced NameNode-reported space from #mib(I.at(0).hdfs_space_consumed_before) to #mib(I.at(0).hdfs_space_consumed_after), with disk measurements in agreement, and all files verified. These figures describe controlled workloads whose duplicates were created deliberately. They verify the mechanism, and they do not predict savings on a real system.

== Technical significance
Three lessons came from running on real HDFS rather than a simulation. Logical savings can mislead: at small chunk sizes, disk use rose even as logical savings improved. Consistency between two independent stores can be achieved by ordering operations carefully, with no shared transaction. And asynchronous behaviour must be observed rather than assumed: `fsck`, JMX caching, block reports and DataNode deletion each surprised an early version of this system, and each was exposed by testing against the real cluster.

== Future possibilities
Content-defined chunking and chunk packing would address the two largest measured weaknesses. A distributed index, parallel scanning with Apache Spark, and deployment on separate machines would make it possible to evaluate the design at a scale this project could not reach.
