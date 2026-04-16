#!/usr/bin/env sh
set -e

wait_consul_up() {
    while ! consul info ; do sleep 1; done
}

"$@" &
wait_consul_up

consul kv put hazelcast_cluster_name "${HAZELCAST_CLUSTER_NAME}"
consul kv put hazelcast_cluster_members "${HAZELCAST_CLUSTER_MEMBERS}"
consul kv put counter_hazelcast_queue_name "${COUNTER_HAZELCAST_QUEUE_NAME}"

wait %%
