#!/usr/bin/env python3

import subprocess

from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus

from interfaces import EtcdProvides, TlsRequires


class KineCharm(CharmBase):
    state = StoredState()

    def __init__(self, framework, parent):
        super().__init__(framework, parent)

        framework.observe(self.on.install, self)
        framework.observe(self.on.upgrade_charm, self)
        framework.observe(self.on.db_relation_changed, self)
        framework.observe(self.on.certificates_relation_joined, self)
        framework.observe(self.on.certificates_relation_changed, self)
        framework.observe(self.on.cluster_relation_joined, self)
        framework.observe(self.on.cluster_relation_changed, self)

        self.etcd = EtcdProvides(self, "db")
        self.tls = TlsRequires(self, "certificates")

    def on_install(self, event):
        if not hasattr(self.state, 'peers'):
            self.state.peers = [self.get_peer_identity('0.0.0.0')]
        if not hasattr(self.state, 'endpoint'):
            self.state.endpoint = None
        subprocess.run(["snap", "install", "kine", "--edge"])
        subprocess.run(["snap", "refresh", "kine", "--edge"])
        self.on_config_changed(event)

    def on_upgrade_charm(self, event):
        self.on_install(event)
        relation = self.framework.model.get_relation('cluster')
        if relation:
            event.relation = relation
            self.on_cluster_relation_joined(event)
            self.on_cluster_relation_changed(event)

    def on_config_changed(self, event):
        endpoint = self.get_dqlite_endpoint()
        if endpoint != self.state.endpoint:
            self.state.endpoint = endpoint
            subprocess.run(["snap", "set", "kine", f"endpoint={endpoint}"])
            subprocess.run(["snap", "set", "kine", f"dqlite-id={self.get_unit_id()}"])
            subprocess.run(["snap", "restart", "kine"])
        self.framework.model.unit.status = ActiveStatus()

    def on_db_relation_changed(self, event):
        ip = event.relation.data[self.framework.model.unit]['ingress-address']
        self.etcd.set_connection_string(f"http://{ip}:2379")

    def on_certificates_relation_joined(self, event):
        self.tls.request_client_cert('cn', [])

    def on_certificates_relation_changed(self, event):
        if not all([self.tls.root_ca_cert, self.tls.client_certs]):
            return

        key = self.tls.client_certs['key']
        cert = self.tls.client_certs['cert']
        ca = self.tls.root_ca_cert
        self.etcd.set_client_credentials(key, cert, ca)

    def on_cluster_relation_joined(self, event):
        unit = self.framework.model.unit
        my_address = event.relation.data[self.framework.model.unit]['ingress-address']
        self.state.my_identity = self.get_peer_identity(my_address)
        event.relation.data[unit]['peer_identity'] = self.state.my_identity

    def on_cluster_relation_changed(self, event):
        self.state.peers = [self.get_peer_identity('0.0.0.0')]
        for unit in event.relation.units:
            if 'peer_identity' not in event.relation.data[unit]:
                continue
            self.state.peers.append(event.relation.data[unit]['peer_identity'])
        self.on_config_changed(event)

    def get_unit_id(self):
        unit = self.framework.model.unit
        unit_num = (int(unit.name.split('/')[1]) % 9) + 1
        return unit_num

    def get_peer_identity(self, address):
        id_ = self.get_unit_id()
        return f"{id_}:{address}:918{id_}"

    def get_dqlite_endpoint(self):
        """Get dqlite connection string, e.g.: dqlite://?peer=1:127.0.0.1:9187

        """
        prefix = "dqlite://?peer="
        peers = '&peer='.join(self.state.peers)
        return prefix + peers


if __name__ == '__main__':
    main(KineCharm)
