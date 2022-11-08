#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# have all voter nodes up all the time

import os
import sys
import itertools
import requests
from pprint import pprint

SUCCESS_EXIT_CODE = 0
ERROR_EXIT_CODE = 1

sites = ['cs', 'phy']
destinations = ['local', 'remote']
node_types = ['master_candidate', 'voter']

def ip_env_var(site, destination, node_type):
  """Form the environment variable name from the function arguments"""
  return f'{destination.upper()}_{site.upper()}_ELASTICSEARCH_{"VOTER_" if node_type == "voter" else ""}IP'

def elastic_ip(site, destination='local', node_type='master_candidate'):
  """Returns the IP address of the node matching the function's arguments"""
  return os.getenv(ip_env_var(site, destination, node_type))

def get_node_states():
  """Iterates through all the nodes we expect to be in our four node cluster to gather information about each"""
  nodes_info = {}
  for site, destination, node_type in itertools.product(sites, destinations, node_types): # every combination
    try:
      node_response = requests.get(f'http://{elastic_ip(site, destination, node_type)}:9200')
      node_name = node_response.json()['name']
      nodes_info[node_name] = {
        'site': site, 'destination': destination, 'node_type': node_type,
        'name': node_name, 'env_var': ip_env_var(site, destination, node_type)
      }
    except requests.exceptions.ConnectionError as e:
      print(
        f'ERROR: ElasticSearch node at {ip_env_var(site, destination, node_type)} is not up. '
        f'Bring it up by typing the following command{" on the REMOTE MACHINE" if destination == "remote" else ""}:\n'
        f'export HOSTNAME && docker-compose up -d {site.lower()}-elasticsearch-{"voter-" if node_type == "voter" else ""}live'
      )
      sys.exit(ERROR_EXIT_CODE)
  return nodes_info

def get_cluster_state():
  """Returns the clusters' states by site"""
  return {site: requests.get(f'http://{elastic_ip(site)}:9200/_cluster/state').json() for site in sites}

def get_node_info_by_id(nodes_info, cluster_info):
  """Combines node and cluster info to get IDs for the nodes and indexes the result by id"""
  nodes_by_id = {}
  for site in sites:
    for node_id, node_details in cluster_info[site]['nodes'].items():
      node_name = node_details['name']
      if node_name in nodes_info:
        nodes_by_id[node_id] = dict(nodes_info[node_name], id=node_id)
      else:
        print(f'ERROR: Found an unexpected node in cluster with name {node_name}. Probably worth stopping and investigating further')
        sys.exit(ERROR_EXIT_CODE)
  return nodes_by_id

def local_is_leader(cluster_info, nodes_by_id):
  """Checks if the cluster coordination settings have more voters on the local machine than the remote machine"""
  local_is_leader_for_all_sites = True
  for site in sites:
    local_score = remote_score = 0
    for node_id in cluster_info[site]['metadata']['cluster_coordination']['last_accepted_config']:
      if nodes_by_id[node_id]['destination'] == 'local':
        local_score += 1
      else:
        remote_score += 1
    local_is_leader_for_all_sites &= local_score > remote_score
  return local_is_leader_for_all_sites

def update_cluster_voting_configuration(cluster_info, nodes_by_id):
  """Clears the excluded voters list and then adds the remote voter to the list for each site's cluster"""
  for site in sites:
    # Clear the voting exclusions list for this site's cluster
    clear_exclusions_response = requests.delete(f'http://{elastic_ip(site)}:9200/_cluster/voting_config_exclusions?wait_for_removal=false')
    if clear_exclusions_response.status_code != 200:
      print("ERROR: Failed to clear voting configuration exclusions list. Run again or try manually")
      pprint(clear_exclusions_response.json())
      sys.exit(ERROR_EXIT_CODE)

    remote_voter_id = None
    for node in nodes_by_id.values():
      if node['site'] == site and node['destination'] == 'remote' and node['node_type'] == 'voter':
        remote_voter_id = node['id']

    if remote_voter_id is None:
      print(f"ERROR: could not find the id of the {site} remote voter to be added to the voting exclusions list")
      sys.exit(ERROR_EXIT_CODE)

    # Add the remote voter ID to the voting exclusions list for this site's cluster
    exclusions_update_response = requests.post(f'http://{elastic_ip(site)}:9200/_cluster/voting_config_exclusions?node_ids={remote_voter_id}')
    if exclusions_update_response.status_code != 200:
      print("ERROR: Failed to add {remote_voter_id} to the voting configuration exclusions list. Run again or try manually")
      pprint(exclusions_update_response.json())
      sys.exit(ERROR_EXIT_CODE)


if __name__ == '__main__':
  nodes_info = get_node_states()
  cluster_info = get_cluster_state()
  nodes_by_id = get_node_info_by_id(nodes_info, cluster_info)

  if local_is_leader(cluster_info, nodes_by_id):
    print("This machine is already the ElasticSearch cluster leader")
    sys.exit(SUCCESS_EXIT_CODE)

  update_cluster_voting_configuration(cluster_info, nodes_by_id)
  
  updated_cluster_info = get_cluster_state()
  if local_is_leader(updated_cluster_info, nodes_by_id):
    print("This machine is the ElasticSearch cluster leader")
    sys.exit(SUCCESS_EXIT_CODE)
  else:
    print("ERROR: The local machine is still NOT the leader, for some reason")
    for site in sites:
      pprint(updated_cluster_info[site]['metadata']['cluster_coordination'])
    sys.exit(ERROR_EXIT_CODE)
