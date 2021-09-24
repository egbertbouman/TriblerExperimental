from tribler_common.simpledefs import STATE_UPGRADING_READABLE
from tribler_core.components.base import Component
from tribler_core.components.implementation.masterkey import MasterKeyComponent
from tribler_core.components.implementation.reporter import ReporterComponent
from tribler_core.components.implementation.restapi import RESTComponent
from tribler_core.upgrade.upgrade import TriblerUpgrader


class UpgradeComponent(Component):
    upgrader: TriblerUpgrader

    async def run(self):
        await self.use(ReporterComponent)
        config = self.session.config
        notifier = self.session.notifier
        master_key_component = await self.use(MasterKeyComponent)
        if not master_key_component:
            self._missed_dependency(MasterKeyComponent.__name__)

        channels_dir = config.chant.get_path_as_absolute('channels_dir', config.state_dir)

        self.upgrader = TriblerUpgrader(
            state_dir=config.state_dir,
            channels_dir=channels_dir,
            trustchain_keypair=master_key_component.keypair,
            notifier=notifier)

        rest_component = await self.use(RESTComponent)
        if not rest_component:
            self._missed_dependency(RESTComponent.__name__)

        rest_component.rest_manager.get_endpoint('upgrader').upgrader = self.upgrader
        rest_component.rest_manager.get_endpoint('state').readable_status = STATE_UPGRADING_READABLE

        await self.upgrader.run()
