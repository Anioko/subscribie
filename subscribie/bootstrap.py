import os
import requests
import json
import yaml

def bootstrap_needed():
  if os.getenv("SUBSCRIBIE_FETCH_JAMLA") is not None and \
    os.path.isfile('/subscribie/volume/bootstrap_complete') is False:
    return True
  else:
    return False

def bootstrap_possible():
  ''' Check if we have all environment vars needed to bootstrap 
    - Can we contact the remote jamla manifest (couchdb)
    - Do we have a shop name?
  '''
  def env_is_set(name):
    if os.getenv(name) is None:
      print("{} not set".format(name))
      return False

  needed = ['COUCH_DB_SERVICE_NAME', 'COUCHDB_USER', 'COUCHDB_PASSWORD', 
            'COUCHDB_DBNAME', 'SUBSCRIBIE_SHOPNAME']
  missing = []
  for envname in needed:
    if env_is_set(envname) is False:
      missing.append(envname)
    if len(missing) is not 0:
      print("Cannot bootstrap")
      return False
  return True

def get_couchdb_con():
  COUCHDB_USER = os.getenv("COUCHDB_USER", 'admin')
  COUCHDB_PASSWORD = os.getenv("COUCHDB_PASSWORD", 'password')
  # If running within cluster, address couchdb by its service name
  if 'COUCH_DB_SERVICE_NAME' in os.environ:
    HOST = ''.join(["http://{}:{}".format(COUCHDB_USER, COUCHDB_PASSWORD), "@",
                  os.getenv('COUCH_DB_SERVICE_NAME'), ":5984/"])
  else:
    HOST = "http://{}:{}@127.0.0.1:5984/".format(COUCHDB_USER, COUCHDB_PASSWORD)

  DBNAME = os.getenv("COUCHDB_DBNAME")
  COUCHDB = HOST + '/' + DBNAME
  return COUCHDB

def bootstrap():
  '''
  Bootstrap a subscribie site whereby the Jamla manifest
  is to be consumed from an external source e.g. a couchdb
  database. We assume a persistant volume is present at path
  "/subscribie/volume" this is used to store the Jamla manifest
  and also mark as bootstrap completed by dropping an empty file
  'bootstrap_complete' in /subscribie/volume.

    - Work out if we need to bootstrap 
      - By checking for SUBSCRIBIE_FETCH_JAMLA environment var
      - and by checking if exists /subscribie/volume/bootstrap_complete
    - Fetch Jamla manifest from external source (assume couchdb)
    - Perform bootstrap
      - Inject Jamla manifest to /subscribie/volume/jamla.yaml
      - Update jamla path in config.py
      - Inject static assets (images, if any, from couchdb attachements) 
    - Mark as bootstrapped
    - continue running as normal
  '''
  if bootstrap_needed() and bootstrap_possible():
    # Fetch jamla from couchdb
    COUCHDB_CON = get_couchdb_con()
    req = requests.get(COUCHDB_CON + '/' + os.getenv("SUBSCRIBIE_SHOPNAME"))
    if req.status_code == 200:
      # Inject Jamla manifest
      jamla = yaml.dump(json.loads(req.text))
      # Write jamla.yaml to PersistentVolume
      with open('/subscribie/volume/jamla.yaml', 'w') as fp:
        fp.write(jamla)
      import pdb;pdb.set_trace()
      pass
    elif req.status_code == 404:
      print("Could not locate jamla manifest from couchdb")
      exit()
    
