# Kine Charm

To prepare this charm for deployment, run the following to install the
framework in to the `lib/` directory:

```
pip install -t lib/ https://github.com/canonical/operator
```

You can then deploy the charm along with Charmed Kubernetes:

```
juju deploy ./bundle.yaml.foo
```
