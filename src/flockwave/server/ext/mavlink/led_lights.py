from __future__ import annotations

from logging import Logger
from struct import Struct
from typing import Optional, TYPE_CHECKING

from flockwave.server.tasks.led_lights import (
    LightConfiguration,
    LightEffectType,
    LEDLightConfigurationManagerBase,
)

from .packets import create_led_control_packet, create_custom_data_packet
from .types import MAVLinkMessageSpecification

__all__ = ("MAVLinkLEDLightConfigurationManager",)

if TYPE_CHECKING:
    from .network import MAVLinkNetwork


# _light_control_packet_struct = Struct("<BBBHB")
_light_control_packet_struct = Struct("<BBBBBBB")
# target_system, R, G, B, light_effect, blink_rate, reserved
_light_brightness_packet_struct = Struct("<BH")


class MAVLinkLEDLightConfigurationManager(
    LEDLightConfigurationManagerBase[MAVLinkMessageSpecification]
):
    """Class that manages the state of the LED lights on the drones when they
    are controlled by commands from the GCS.
    """

    def __init__(self, network: "MAVLinkNetwork"):
        """Constructor.

        Parameters:
            network: the network whose LED lights this object manages
        """
        super().__init__()
        self._network: "MAVLinkNetwork" = network

    def _create_light_control_packet(
        self, config: LightConfiguration, target_system: int = 0
    ) -> Optional[MAVLinkMessageSpecification]:
        """Creates a MAVLink message specification for the MAVLink message that
        we need to send to all the drones in order to instruct them to do the
        current light effect.
        """
        # is_active = config.effect == LightEffectType.SOLID
        # data = _light_control_packet_struct.pack(
        #     config.color[0],
        #     config.color[1],
        #     config.color[2],
        #     (
        #         30000  # drone will switch back to normal mode after 30 sec
        #         if is_active
        #         else 0
        #     ),  # submitting zero duration turns off any effect that we have
        #     1 if is_active else 0,
        # )

        # return create_led_control_packet(data, broadcast=True)

        if config is None:
            return None

        # Convert effect type to a numeric value
        light_effect = 0
        if config.effect == LightEffectType.SOLID:
            light_effect = 1

        data = _light_control_packet_struct.pack(
            target_system,
            0,  # flag
            config.color[0],  # R
            config.color[1],  # G
            config.color[2],  # B
            light_effect,
            config.blink_rate,
        )

        return create_custom_data_packet(96, data)

    # async def _send_light_control_packet_v2(
    #     self, packet: MAVLinkMessageSpecification, target_system: int = 0
    # ) -> None:
    #     """Sends a v2 light control packet to the specified target system.

    #     Parameters:
    #         packet: the packet to send
    #         target_system: the target system ID (0 for broadcast)
    #     """
    #     if target_system == 0:
    #         # Broadcast to all systems
    #         return await self._network.broadcast_packet(packet)
    #     else:
    #         # Send to specific system
    #         return await self._network.send_packet(packet, target_system=target_system)

    def _get_logger(self) -> Optional[Logger]:
        return self._network.log if self._network else None

    async def _send_light_control_packet(
        self, packet: MAVLinkMessageSpecification
    ) -> None:
        return await self._network.broadcast_packet(packet)
