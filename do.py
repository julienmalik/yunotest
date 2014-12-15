# -*- coding: utf-8 -*-

import sys
import os
import random
import json
import subprocess
import re
import urllib
import copy
import time
import pexpect
import string

from contextlib import contextmanager

def make_test_domain():
  prefix = 'yunotest-'
  suffix = '.nohost.me'
  id = random.randint(1, 100000)
  return '%s%06d%s' % (prefix, id, suffix)

def make_random_password(length=32):
  choices = string.ascii_uppercase + string.ascii_lowercase + string.digits
  return ''.join(random.choice(choices) for _ in range(length))

class DigitalOceanServer:
  def __init__(self, domain, admin_password, doyunohost_path):
    self.domain = domain
    self.admin_password = admin_password
    self.doyunohost_path = doyunohost_path

  def deploy(self):
    print('Starting to deploy DigitalOcean server %s' % (self.domain))
    command = "python %s/deploy.py --domain %s --password %s" \
       % (self.doyunohost_path, self.domain, self.admin_password)
    self.run_local_cmd(command)
    print('Successfully deployed DigitalOcean server %s' % (self.domain))

  def remove(self):
    print('Removing DigitalOcean server %s' % (self.domain))
    command = "python %s/remove.py --domain %s" % (self.doyunohost_path, self.domain)
    self.run_local_cmd(command)
    print('Successfully removed DigitalOcean server %s' % (self.domain))

  def run_local_cmd(self, command):
    print('> %s' % (command))
    #exit_code = os.system(command)
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    while 1:
      line = process.stdout.readline()
      if not line:
        break
      if line.endswith('\n'):
        line = line[:-1]
      print line
    exit_code = process.returncode
    print('< exit code : %s' % (exit_code))

  def run_remote_cmd(self, command, user='root'):
    ssh_command = 'ssh -t -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no "%s@%s" "export TERM=linux; %s"' \
      % (user, self.ip, command)
    print('> %s' % (ssh_command))
    (output, exit_code) = pexpect.run(ssh_command, withexitstatus=True, timeout= 10*60, \
      events={'Administration password:':'%s\n' % (self.admin_password)})
    print(output)
    print('< exit code: %s' % (exit_code))
    return (output, exit_code)

  def setup(self):
    self.retrieve_ip()
    self.init_admin_account()
    self.run_remote_cmd("yunohost user create -f Theodocle -l Chancremou -p grumpf -m 'theodocle.chancremou@%s' theodocle" \
      % (self.domain), 'admin')

  def retrieve_ip(self):
    print('Retrieving IP for %s' % (self.domain))
    
    # wait for a maximum of 5 min
    timeout = 5 * 60
    start_time = time.time()
    current_time = 0
    while current_time < timeout and not hasattr(self, 'ip'):
      current_time = time.time()-start_time
      
      command = "dig +short @dynhost.yunohost.org %s" % (self.domain)
      print '> %s' % (command)
      (output, exit_status) = pexpect.run(command, withexitstatus=True)
      
      # http://glowingpython.blogspot.fr/2011/06/searching-for-ip-address-using-regular.html
      ip_re = re.compile('(([2][5][0-5]\.)|([2][0-4][0-9]\.)|([0-1]?[0-9]?[0-9]\.)){3}'
                         +'(([2][5][0-5])|([2][0-4][0-9])|([0-1]?[0-9]?[0-9]))')
      match = ip_re.search(output)
      if match:
        self.ip = match.group()
      
      # sleep for 15s
      time.sleep(15)
      
    if current_time >= timeout:
      raise RuntimeError("Timeout expired when trying to get IP address for %s" % (self.domain))
    else:
      print('IP retrieved in %s s' % current_time)
      
  def init_admin_account(self):
    # init account creation
    self.run_remote_cmd("su - admin")
    
    # copy ssh keys
    self.run_remote_cmd("cp -r /root/.ssh /home/admin")
    self.run_remote_cmd("chown -R admin: /home/admin/.ssh")
    
    # try to connect as admin via ssh
    self.run_remote_cmd("pwd", 'admin')

  def install_app(self, test_prop):
    test_prop_resolved = {}
    for key, value in test_prop['install'].items():
      test_prop_resolved[key] = value \
         .replace('${MAIN_DOMAIN}', self.domain) \
         .replace('${USER}', 'theodocle') \
         .replace('${RANDOM_PASSWORD}', make_random_password())
    install_args = urllib.urlencode(test_prop_resolved)
    install_command = "yunohost app install '%s' -a '%s'" % (test_prop['git'], install_args)
    return self.run_remote_cmd(install_command, 'admin')
    
  def remove_app(self, test_prop):
    remove_command = "yunohost app remove %s" % (test_prop['id'])
    return self.run_remote_cmd(remove_command, 'admin')

# http://preshing.com/20110920/the-python-with-statement-by-example/
@contextmanager
def deploy(do_server):
  do_server.deploy()
  try:
    yield do_server
  finally:
    do_server.remove()
