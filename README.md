# isaac-elasticsearch-cluster
A repository to hold the ElasticSearch configuration and scripts used to support the Isaac platform.

At Isaac we currently self-host on-prem and have our services on two machines in a leader/follower configuration to support high availability and failovers.
ElasticSearch clusters can include *n* nodes but require more than two nodes for its master-eligible nodes to run a successful election and decide on the new master in the case of a partition. We run one master-eligible data node and one voting-only node on each machine and manually set the voting exclusion list so that the leading machine gets two votes to the follower machine's one.
In this configuration if the follower machine is down, the leader's two nodes can still hold an election and therefore accept writes.
If the leader machine is down, the nodes on the follower machine would be read-only (although we currently choose to hold a "down for maintenance" page instead). 

## To bring up the containers initially
We need to follow a slightly different procedure to set up the cluster for the very first time to support ElasticSearch's bootstrapping procedure.

Uncomment the lines in **docker-compose.yml** which look like the following:
```yaml
- "cluster.initial_master_nodes=${HOSTNAME}-phy-node"
# ...
- "cluster.initial_master_nodes=${HOSTNAME}-cs-node"
```

Then ask docker to create the containers.
```bash
export HOSTNAME
docker-compose up -d
```
> The `export HOSTNAME` command leads to nicer node names which help when reviewing logs / writing scripts.

Clean up the temporary uncommented changes:
```bash
git checkout docker-compose.yml
```

This procedure will need to happen on each of the two machines.

Finally, on the lead machine, run:
```bash
./make-leader
```
> You might need to `chmod` **make-leader.py** so that it can be treated as an executable.

## To switch leader 
Run the following command on the machine that you want to be the new leader:
```bash
./make-leader.py
```
> You might need to `chmod` **make-leader.py** so that it can be treated as an executable.
