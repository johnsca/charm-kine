#!/usr/bin/env python3

import os
import sys
from pathlib import Path

import yaml

CHARM_STATE_FILE = '.unit-state.db'


def debugf(format, *args, **kwargs):
    pass


def _get_charm_dir():
    charm_dir = os.environ.get("JUJU_CHARM_DIR")
    if charm_dir is None:
        # Assume $JUJU_CHARM_DIR/lib/juju/main.py structure.
        charm_dir = Path(f'{__file__}/../../..').resolve()
    else:
        charm_dir = Path(charm_dir).resolve()
    return charm_dir


def _load_metadata(charm_dir):
    with open(charm_dir / 'metadata.yaml') as f:
        metadata = yaml.load(f, Loader=yaml.SafeLoader)
    return metadata


def _handle_event_link(charm_dir, bound_event):
    """Create a symlink for a particular event.

    charm_dir -- A root directory of the charm
    bound_event -- An event for which to create a symlink.
    """
    from juju.charm import InstallEvent

    if issubclass(bound_event.event_type, InstallEvent):
        # We don't set up the link for install events, since we assume it's already in place
        # (otherwise, we would never have been called).
        return

    event_hook_path = charm_dir / 'hooks' / bound_event.event_kind.replace('_', '-')
    create_link = True
    # Remove incorrect symlinks or files.
    if event_hook_path.exists():
        # Non-symlink entries and the ones not pointing to "install"
        # need to be removed.
        if not event_hook_path.is_symlink():
            debugf(f'Hook entry at {event_hook_path} is not a symlink:'
                   ' attempting to remove it.')
            # May raise IsADirectoryError, e.g. in case it is a directory which
            # is unexpected and left to the developer or operator to handle.
            event_hook_path.unlink()
        elif os.readlink(event_hook_path) != 'install':
            debugf(f'Removing entry {event_hook_path} as it does not point'
                   ' to "install"')
            event_hook_path.unlink()
        else:
            create_link = False

    if create_link:
        debugf(f'Creating a new relative symlink at {event_hook_path}'
               f' to pointing to "install" located in {charm_dir}/hooks')
        event_hook_path.symlink_to('install')


def _setup_hooks(charm_dir, charm):
    """Set up hooks for supported events.

    Whether a charm can handle an event or not can be determined by
    introspecting which events are defined on it.

    Hooks are created as symlinks to "install" which may be either
    a copy of main.py (which calls the main function) or a symlink
    to it. Note that it is important to avoid creating a recursive
    symlink which is why the install event itself is skipped.

    charm_dir -- A root directory of the charm.
    charm -- An instance of the Charm class.
    """
    from juju.charm import HookEvent

    for bound_event in charm.on.events().values():
        if issubclass(bound_event.event_type, HookEvent):
            _handle_event_link(charm_dir, bound_event)


def _emit_charm_event(charm, event_name):
    """Emits a charm event based on a Juju event name.

    charm -- A charm instance to emit an event from.
    event_name -- A Juju event name to emit on a charm.
    """
    formatted_event_name = event_name.replace('-', '_')
    event_to_emit = None
    try:
        event_to_emit = getattr(charm.on, formatted_event_name)
    except AttributeError:
        debugf(f"event {formatted_event_name} not defined for {charm}")

    # If the event is not supported by the charm implementation, do
    # not error out or try to emit it. This is to support rollbacks.
    if event_to_emit is not None:
        args, kwargs = _get_event_args(charm, event_to_emit)
        debugf(f'Emitting Juju event {event_name}')
        event_to_emit.emit(*args, **kwargs)


def _get_event_args(charm, bound_event):
    import juju.charm
    event_type = bound_event.event_type
    model = charm.framework.model
    if issubclass(event_type, juju.charm.RelationEvent):
        relation_name = os.environ['JUJU_RELATION']
        relation_id = int(os.environ['JUJU_RELATION_ID'].split(':')[-1])
        relation = model.get_relation(relation_name, relation_id)
        if issubclass(event_type, juju.charm.RelationUnitEvent):
            remote_unit_name = os.environ['JUJU_REMOTE_UNIT']
            remote_unit = model.get_unit(remote_unit_name)
            return [relation, remote_unit], {}
        else:
            return [relation], {}
    return [], {}


def main():
    """Setup the charm and dispatch the observed event.

    The event name is based on the way this executable was called (argv[0]).
    """
    import charm as charm_module
    import juju.charm
    import juju.framework
    import juju.model

    charm_dir = _get_charm_dir()

    # Process the Juju event relevant to the current hook execution
    # JUJU_HOOK_NAME or JUJU_ACTION_NAME are not used to support simulation
    # of events from debugging sessions.
    juju_event_name = Path(sys.argv[0]).name

    meta = juju.charm.CharmMeta(_load_metadata(charm_dir))
    unit_name = os.environ['JUJU_UNIT_NAME']
    model = juju.model.Model(unit_name, list(meta.relations), juju.model.ModelBackend())

    # TODO: If Juju unit agent crashes after exit(0) from the charm code
    # the framework will commit the snapshot but Juju will not commit its
    # operation.
    charm_state_path = charm_dir / CHARM_STATE_FILE
    framework = juju.framework.Framework(charm_state_path, charm_dir, meta, model)
    try:
        # TODO: The Charm itself sholud probably receive no other argument than the framework, because
        # this will be code that the user will need to implement on their end. In other words, their
        # Charm subclass will have an __init__, which needs to take parameters, and this needs to be
        # simple and elegant so it doesn't feel hackish.
        charm = charm_module.Charm(framework, None)

        # When a charm is force-upgraded and a unit is in an error state Juju does not run upgrade-charm and
        # instead runs the failed hook followed by config-changed. Given the nature of force-upgrading
        # the hook setup code is not triggered on config-changed.
        if (juju_event_name in ('install', 'upgrade-charm') or juju_event_name.endswith('-storage-attached')):
            _setup_hooks(charm_dir, charm)

        framework.reemit()

        _emit_charm_event(charm, juju_event_name)

        framework.commit()
    finally:
        framework.close()


def _setup_path():
    # The first element is the directory containing this file. We don't want that in the path.
    del sys.path[0]
    # Add $JUJU_CHARM_DIR/lib to the path.
    sys.path.insert(0, str(_get_charm_dir() / 'lib'))


if __name__ == '__main__':
    _setup_path()
    main()
