import json
from ops.framework import Object


class EtcdProvides(Object):
    def __init__(self, parent, key):
        super().__init__(parent, key)
        self.name = key

    def set_client_credentials(self, key, cert, ca):
        ''' Set the client credentials on the global conversation for this
        relation. '''
        unit = self.framework.model.unit
        for relation in self.framework.model.relations[self.name]:
            relation.data[unit]['client_key'] = key
            relation.data[unit]['client_cert'] = cert
            relation.data[unit]['client_ca'] = ca

    def set_connection_string(self, connection_string, version='3.'):
        ''' Set the connection string on the global conversation for this
        relation. '''
        unit = self.framework.model.unit
        for relation in self.framework.model.relations[self.name]:
            relation.data[unit]['connection_string'] = connection_string
            relation.data[unit]['version'] = version


class TlsRequires(Object):
    def __init__(self, parent, key):
        super().__init__(parent, key)
        self.name = key

    def request_client_cert(self, cn, sans):
        """
        Request a client certificate and key be generated for the given
        common name (`cn`) and list of alternative names (`sans`).

        This can be called multiple times to request more than one client
        certificate, although the common names must be unique.  If called
        again with the same common name, it will be ignored.
        """
        relations = self.framework.model.relations[self.name]
        if not relations:
            return
        # assume we'll only be connected to one provider
        relation = relations[0]
        unit = self.framework.model.unit
        requests = relation.data[unit].get('client_cert_requests', '{}')
        requests = json.loads(requests)
        requests[cn] = {'sans': sans}
        relation.data[unit]['client_cert_requests'] = json.dumps(requests, sort_keys=True)

    @property
    def root_ca_cert(self):
        """
        Root CA certificate.
        """
        # only the leader of the provider should set the CA, or all units
        # had better agree
        for relation in self.framework.model.relations[self.name]:
            for unit in relation.units:
                if relation.data[unit].get('ca'):
                    return relation.data[unit].get('ca')

    @property
    def client_certs(self):
        """
        List of [Certificate][] instances for all available client certs.
        """
        unit_name = self.framework.model.unit.name.replace('/', '_')
        field = '{}.processed_client_requests'.format(unit_name)

        for relation in self.framework.model.relations[self.name]:
            for unit in relation.units:
                if field not in relation.data[unit]:
                    continue
                certs_data = relation.data[unit][field]
                if not certs_data:
                    continue
                certs_data = json.loads(certs_data)
                if not certs_data:
                    continue
                return list(certs_data.values())[0]
