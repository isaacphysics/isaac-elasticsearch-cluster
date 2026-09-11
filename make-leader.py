#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# !!! export HOSTNAME before running this !!!
# have all voter nodes up all the time

import os
import re
import sys
import requests
from pprint import pprint
import base64


SUCCESS_EXIT_CODE = 0
ERROR_EXIT_CODE = 1

sites = ['sci', 'ada']

site_password = {
  'sci': os.getenv('SCI_ELASTIC_PASSWORD'),
  'ada': os.getenv('ADA_ELASTIC_PASSWORD')
}

def auth_header(site):
  token = f'elastic:{site_password[site]}'.encode()
  return {'Authorization': f'Basic {base64.b64encode(token).decode("utf8")}'}

def ip_env_var(site):
  """Form the local master candidate ES IP environment variable name for the specified site"""
  return f'LOCAL_{site.upper()}_ELASTICSEARCH_V9_IP'

def elastic_ip(site):
  """Returns the IP address of the local master candidate node for the specified site"""
  return os.getenv(ip_env_var(site))

def get_cluster_state():
  """Returns the clusters' states by site"""
  return {site: requests.get(f'http://{elastic_ip(site)}:9200/_cluster/state', headers=auth_header(site)).json() for site in sites}

def get_node_info_by_id(cluster_info):
  """Uses cluster info to get IDs & names for the nodes and indexes the result by ID"""
  nodes_by_id = {}
  for site in sites:
    for node_id, node_details in cluster_info[site]['nodes'].items():
      node_name = node_details['name']
      match = re.compile(r'^(?P<hostname>.+)-(?P<site>' + '|'.join(sites) + r')-(?P<voter>voter-)?node$').match(node_name)
      if match is None:
        print(f'ERROR: Found an unexpected node in cluster with name {node_name}. Probably worth stopping and investigating further')
        sys.exit(ERROR_EXIT_CODE)
      node_type = 'voter' if match.group('voter') else 'master_candidate'
      destination = 'local' if match.group('hostname') == os.getenv('HOSTNAME') else 'remote'
      nodes_by_id[node_id] = {'site': site, 'destination': destination, 'node_type': node_type, 'name': node_name, 'id': node_id}
  return nodes_by_id

def local_is_leader(cluster_info, nodes_by_id):
  """Checks if the cluster coordination settings have more voters on the local machine than the remote machine"""
  local_is_leader_for_all_sites = True
  for site in sites:
    local_score = remote_score = 0
    for node_id in cluster_info[site]['metadata']['cluster_coordination']['last_accepted_config']:
      if nodes_by_id.get(node_id, {'destination': None})['destination'] == 'local':
        local_score += 1
      elif nodes_by_id.get(node_id, {'destination': None})['destination'] == 'remote':
        remote_score += 1
    local_is_leader_for_all_sites &= local_score > remote_score
  return local_is_leader_for_all_sites

def update_cluster_voting_configuration(nodes_by_id):
  """Clears the excluded voters list and then adds the remote voter to the list for each site's cluster"""
  for site in sites:
    # Clear the voting exclusions list for this site's cluster
    clear_exclusions_response = requests.delete(f'http://{elastic_ip(site)}:9200/_cluster/voting_config_exclusions?wait_for_removal=false', headers=auth_header(site))
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
    exclusions_update_response = requests.post(f'http://{elastic_ip(site)}:9200/_cluster/voting_config_exclusions?node_ids={remote_voter_id}', headers=auth_header(site))
    if exclusions_update_response.status_code != 200:
      print("ERROR: Failed to add {remote_voter_id} to the voting configuration exclusions list. Run again or try manually")
      pprint(exclusions_update_response.json())
      sys.exit(ERROR_EXIT_CODE)


if __name__ == '__main__':
  cluster_info = get_cluster_state()
  nodes_by_id = get_node_info_by_id(cluster_info)

  if local_is_leader(cluster_info, nodes_by_id):
    print("This machine is already the ElasticSearch cluster leader")
    sys.exit(SUCCESS_EXIT_CODE)

  update_cluster_voting_configuration(nodes_by_id)
  
  updated_cluster_info = get_cluster_state()
  if local_is_leader(updated_cluster_info, nodes_by_id):
    print("This machine is the ElasticSearch cluster leader")
    sys.exit(SUCCESS_EXIT_CODE)
  else:
    print("ERROR: The local machine is still NOT the leader, for some reason")
    for site in sites:
      pprint(updated_cluster_info[site]['metadata']['cluster_coordination'])
    sys.exit(ERROR_EXIT_CODE)
