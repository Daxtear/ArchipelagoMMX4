import asyncio
import logging
import time
import uuid
from typing import TYPE_CHECKING

from NetUtils import ClientStatus

import worlds._bizhawk as bizhawk
from worlds._bizhawk.client import BizHawkClient
from worlds._bizhawk import get_memory_size

if TYPE_CHECKING:
    from worlds._bizhawk.context import BizHawkClientContext

logger = logging.getLogger("Client")

# MMX4_ARCHIPELAGO
ADDRESS_PATCH_NAME = 0x0F1740
# Items
ADDRESS_STAGE_ACCESS = 0x0F1750
ADDRESS_ARMOR_FLAGS = 0x0F1770
ADDRESS_ARMS_FLAGS = 0x0F1771
ADDRESS_MAX_HEALTH = 0x0F1772
ADDRESS_CURRENT_HEALTH = 0x141924
ADDRESS_ACTION_STATE = 0x1418CC
ADDRESS_NOVA_STRIKE_ENERGY = 0x141970
ADDRESS_LIFE_COUNT = 0x172204
ADDRESS_WEAPONS_FLAGS = 0x0F1773
ADDRESS_TANK_FLAGS = 0x0F1774
# Locations
ADDRESS_ARMOR_PICKED_UP = 0x0F1790
ADDRESS_BOSSES_DEFEATED = 0x0F17A0
ADDRESS_ITEMS_PICKED_UP = 0x0EE558
# Button Presses
ADDRESS_SELECT_PRESSED = 0x166C09
# SELECTED WEAPON
ADDRESS_WEAPON_SELECTED = 0x14195B

# DamageLink conversion. Matches Mega Man X community DamageLink behavior:
# 10 shared-damage points = 1 MMX4 HP.
DAMAGE_LINK_POINTS_PER_HP = 10
DAMAGE_LINK_NORMAL_CAP_POINTS = 120

# Location ids that are awarded by boss/stage defeat flags.
# When one of these appears newly, MMX4 is entering a clear/results flow where
# current HP can briefly become 0 even though the player did not die.
DEFEATED_LOCATION_IDS = {
    14574100, 14574101, 14574104, 14574105, 14574109, 14574110,
    14574114, 14574115, 14574118, 14574119, 14574122, 14574123,
    14574125, 14574126, 14574128, 14574129, 14574133, 14574134,
    14574135, 14574136, 14574137, 14574138, 14574139, 14574140,
    14574141, 14574142, 14574143, 14574144, 14574145, 14574146,
    14574300,
}

# Received AP filler items that should feed EnergyLink.
ITEM_SMALL_ENERGY = 14575300
ITEM_LARGE_ENERGY = 14575301
ITEM_SMALL_WEAPON_ENERGY = 14575302
ITEM_LARGE_WEAPON_ENERGY = 14575303
ENERGY_LINK_PICKUP_VALUES = {
    ITEM_SMALL_ENERGY: 5,
    ITEM_LARGE_ENERGY: 20,
    ITEM_SMALL_WEAPON_ENERGY: 3,
    ITEM_LARGE_WEAPON_ENERGY: 10,
    14575304: 100,  # Extra Life filler item
    14575116: 100,  # Extra Lives Tank AP item
    14575114: 150,  # Sub Tank AP item
}

# Item-data pointers written by the MMX4 patch when in-game pickups are collected.
# These are used for EnergyLink rewards from pickup checks and re-pickups.
PICKUP_POINTER_TO_LOCATION_ID = {
    0x800F4D30: 14574200,  # Intro Stage Life Energy (1)
    0x800F4D40: 14574201,  # Intro Stage Max Life Energy (1)
    0x800F4D38: 14574202,  # Intro Stage 1 Up (1)
    0x800F52B0: 14574203,  # Web Spider Life Energy (1)
    0x800F52C0: 14574204,  # Web Spider Max Life Energy (1)
    0x800F52B8: 14574103,  # Web Spider Heart Tank
    0x800F7438: 14574106,  # Cyber Peacock Heart Tank
    0x800F7440: 14574107,  # Cyber Peacock Sub Tank
    0x800F7700: 14574205,  # Storm Owl Life Energy (1)
    0x800F7978: 14574206,  # Storm Owl Max Life Energy (1)
    0x800F76F8: 14574111,  # Storm Owl Heart Tank
    0x800F6854: 14574116,  # Magma Dragoon Heart Tank
    0x800F66B4: 14574207,
    0x800F66BC: 14574208,
    0x800F685C: 14574209,
    0x800F6C40: 14574120,  # Jet Stingray Heart Tank
    0x800F6E98: 14574121,  # Jet Stingray Sub Tank
    0x800F6EA0: 14574210,
    0x800F6320: 14574124,  # Split Mushroom Heart Tank
    0x800F6328: 14574211,
    0x800F6330: 14574212,
    0x800F7D3C: 14574127,  # Slash Beast Heart Tank
    0x800F7D44: 14574213,
    0x800F56C0: 14574214,
    0x800F56C8: 14574215,
    0x800F56B8: 14574216,
    0x800F56B0: 14574217,
    0x800F5660: 14574218,  # Frost Walrus 1 Up (1)
    0x800F5680: 14574219,
    0x800F5688: 14574220,
    0x800F5690: 14574221,
    0x800F5698: 14574222,
    0x800F56A0: 14574223,
    0x800F56A8: 14574224,
    0x800F5668: 14574225,  # Frost Walrus 1 Up (2)
    0x800F5678: 14574226,
    0x800F5868: 14574227,
    0x800F5658: 14574130,  # Frost Walrus Heart Tank
    0x800F5670: 14574131,  # Frost Walrus Extra Lives Tank
    0x800F5860: 14574132,  # Frost Walrus Weapon Tank
    0x800F86CC: 14574228,
    0x800F8564: 14574229,
    0x800F855C: 14574230,
    0x800F87E0: 14574231,
    0x800F87E8: 14574232,
    0x800F87F0: 14574233,
    0x800F87F8: 14574234,
    0x800F8910: 14574235,
    0x800F8918: 14574236,
    0x800F8920: 14574237,
}

REPEATABLE_PICKUP_ENERGY_VALUES = {
    # Small/large life energy and weapon energy pickups can be collected again, so every new pickup-log entry pays.
    14574200: 5, 14574203: 5, 14574205: 5, 14574207: 5, 14574208: 5, 14574209: 5,
    14574211: 5, 14574216: 5, 14574217: 5, 14574219: 5, 14574220: 5, 14574221: 5,
    14574222: 5, 14574223: 5, 14574224: 5, 14574228: 5, 14574232: 5, 14574233: 5, 14574237: 5,
    14574201: 20, 14574204: 20, 14574206: 20, 14574210: 20, 14574213: 20, 14574226: 20,
    14574229: 20, 14574230: 20, 14574231: 20, 14574235: 20,
    14574212: 3, 14574214: 3, 14574215: 3, 14574234: 3,
    14574227: 10, 14574236: 10,
    14574202: 100, 14574218: 100, 14574225: 100,  # 1 Ups
    14574131: 100,  # Extra Lives Tank check
}

ONCE_PICKUP_ENERGY_VALUES = {
    14574107: 150,  # Cyber Peacock Sub Tank check
    14574121: 150,  # Jet Stingray Sub Tank check
}

ITEM_ID_TO_NAME = {
    14575100: "Lightning Web",
    14575101: "Aiming Laser",
    14575102: "Double Cyclone",
    14575103: "Rising Fire",
    14575104: "Ground Hunter",
    14575105: "Soul Body",
    14575106: "Twin Slasher",
    14575107: "Frost Tower",
    14575108: "Helmet Upgrade",
    14575109: "Body Upgrade",
    14575110: "Plasma Shot Upgrade",
    14575111: "Stock Charge Upgrade",
    14575112: "Legs Upgrade",
    14575113: "Heart Tank",
    14575114: "Sub Tank",
    14575115: "Weapon Energy Tank",
    14575116: "Extra Lives Tank",
    14575200: "Web Spider Stage Access",
    14575201: "Cyber Peacock Stage Access",
    14575202: "Storm Owl Stage Access",
    14575203: "Magma Dragoon Stage Access",
    14575204: "Jet Stingray Stage Access",
    14575205: "Split Mushroom Stage Access",
    14575206: "Slash Beast Stage Access",
    14575207: "Frost Walrus Stage Access",
    14575300: "Small Energy",
    14575301: "Large Energy",
    14575302: "Small Weapon Energy",
    14575303: "Large Weapon Energy",
    14575304: "Extra Life",
    14575400: "Victory",
}

class MMX4Client(BizHawkClient):
    game = "Mega Man X4"
    system = "PSX"
    weapon = 0

    def __init__(self) -> None:
        self.ram = "MainRAM"
        self.slot_data = {}
        self.last_hp = None
        self.damage_link_uuid = str(uuid.uuid4())
        self.ignore_next_damage = False
        self.ignore_next_death = False
        self.force_death_pending = False
        self.deathlink_suppress_outgoing_until = 0.0
        self.pending_life_reset_until = 0.0
        self.pending_life_reset_value = 0
        self.pending_damage = 0
        self.pending_damage_point_remainder = 0
        self.needs_tag_update = False
        self.needs_energy_setup = False
        self.last_energy_pool = None
        self.last_energy_status_text = ""
        self.last_energy_ui_time = 0.0
        self.energy_ui_interval = 5.0
        self.processed_energy_item_count = 0
        self.processed_energy_item_keys = set()
        self.processed_pickup_log_entries = set()
        self.energy_once_locations_paid = set()
        self.current_hp = None
        self.current_lives = None
        self.last_life_count = None
        self.deathlink_amnesty_lives = 0
        self.initial_tutorial_amnesty_applied = False
        self.extra_lives_tank_count = 0
        self.current_max_hp = 32
        self.current_energy_pool = 0
        self.was_in_level = False
        self.inventory_tab = None
        self.inventory_box = None
        self.inventory_expanded = True
        self.gui_tab_attach_tried = False
        self.stage_clear_cooldown_until = 0.0
        self.last_bosses_defeated_bytes = None
        self.previous_defeated_locations_seen = set()
        self.stage_clear_suppress_until_positive_hp = False

    async def validate_rom(self, ctx: "BizHawkClientContext") -> bool:
        try:
            # Check memory size first
            if (await get_memory_size(ctx.bizhawk_ctx, self.ram)) < 0x0F1870:
                return False
            # Check ROM name/patch version
            rom_name = ((await bizhawk.read(ctx.bizhawk_ctx, [(ADDRESS_PATCH_NAME, 0x10, self.ram)]))[0])
            rom_name = rom_name.decode("ascii")
            if rom_name != "MMX4_ARCHIPELAGO":
                return False  # Not our patched ROM
        except bizhawk.RequestFailedError:
            return False  # Not able to get a response, say no for now

        ctx.game = self.game
        ctx.items_handling = 0b111
        ctx.want_slot_data = True
        return True

    def on_package(self, ctx, cmd: str, args: dict) -> None:
        if cmd == "Connected":
            self.slot_data = args.get("slot_data", {}) or {}
            self._register_heal_command(ctx)

            if self.slot_data.get("death_link", False):
                ctx.tags.add("DeathLink")

            if self.slot_data.get("damage_link", False):
                ctx.tags.add("SharedDamage")

            if self.slot_data.get("energy_link", False):
                ctx.tags.add("EnergyLink")
                self.needs_energy_setup = True

            self.needs_tag_update = True

        elif cmd == "Retrieved" and "keys" in args:
            energy_key = f"EnergyLink{ctx.team}"
            if energy_key in args.get("keys", {}):
                try:
                    self.current_energy_pool = int(args["keys"].get(energy_key, 0) or 0)
                except (TypeError, ValueError):
                    self.current_energy_pool = 0
                self._update_inventory_tab_safe(ctx)

        elif cmd == "Bounced" and "tags" in args and "data" in args:
            tags = args.get("tags", [])
            data = args.get("data", {})

            if data.get("uuid") == self.damage_link_uuid:
                return

            if "DeathLink" in tags and "DeathLink" in ctx.tags:
                # Incoming DeathLink should kill the player, but must not bounce
                # another outgoing DeathLink when the life counter changes.
                self.force_death_pending = True
                self.deathlink_suppress_outgoing_until = time.time() + 8.0
                self.pending_life_reset_value = self._deathlink_amnesty_value()
                self.pending_life_reset_until = time.time() + 8.0

            if "SharedDamage" in tags and "SharedDamage" in ctx.tags:
                # Incoming DamageLink is measured in shared-damage points.
                # 10 points converts into 1 MMX4 HP of damage. Remainders are
                # kept so several small hits can eventually cross the threshold.
                amount = int(data.get("amount", data.get("damage", 1)) or 1)
                self.pending_damage += max(1, amount)

    def _slot_option_enabled(self, name: str) -> bool:
        return bool((self.slot_data or {}).get(name, False))

    def _deathlink_amnesty_value(self) -> int:
        try:
            base_amnesty = max(1, min(255, int((self.slot_data or {}).get("death_link_amnesty", 3) or 3)))
        except (TypeError, ValueError):
            base_amnesty = 3

        # The Extra Lives Tank gives 2 extra safe deaths. Keep this separate
        # from the YAML base value so the option remains the starting amnesty.
        extra_tank_bonus = max(0, int(getattr(self, "extra_lives_tank_count", 0))) * 2
        return max(1, min(255, base_amnesty + extra_tank_bonus))

    async def _read_current_hp(self, ctx: "BizHawkClientContext") -> int:
        return (await bizhawk.read(ctx.bizhawk_ctx, [(ADDRESS_CURRENT_HEALTH, 1, self.ram)]))[0][0]

    async def _read_life_count(self, ctx: "BizHawkClientContext") -> int:
        return (await bizhawk.read(ctx.bizhawk_ctx, [(ADDRESS_LIFE_COUNT, 1, self.ram)]))[0][0]

    async def _write_life_count(self, ctx: "BizHawkClientContext", value: int) -> None:
        await bizhawk.write(ctx.bizhawk_ctx, [(ADDRESS_LIFE_COUNT, [max(0, min(255, int(value)))], self.ram)])

    async def _write_current_hp(self, ctx: "BizHawkClientContext", value: int) -> None:
        await bizhawk.write(ctx.bizhawk_ctx, [(ADDRESS_CURRENT_HEALTH, [max(0, min(255, int(value)))], self.ram)])

    async def _force_player_death(self, ctx: "BizHawkClientContext") -> None:
        # MMX4 action / animation state 0x03 is the dying/dead state.
        # This is more reliable for received DeathLink than only setting HP to 0.
        await bizhawk.write(ctx.bizhawk_ctx, [(ADDRESS_ACTION_STATE, [0x03], self.ram)])

    def _energy_key(self, ctx: "BizHawkClientContext") -> str:
        return f"EnergyLink{ctx.team}"

    def _get_energy_pool(self, ctx: "BizHawkClientContext") -> int:
        try:
            self.current_energy_pool = int(ctx.stored_data.get(self._energy_key(ctx), 0) or 0)
        except (TypeError, ValueError, AttributeError):
            self.current_energy_pool = 0
        return self.current_energy_pool

    def _is_hp_value_in_level(self, current_hp: int, max_health_value: int) -> bool:
        """
        MMX4's active HP address is only safe while gameplay is active.
        This guard is used for HP-based systems like EnergyLink healing and
        DamageLink. DeathLink no longer uses HP at all; it is life-counter based.
        """
        if time.time() < self.stage_clear_cooldown_until and current_hp <= 0:
            return False
        if 0 < current_hp <= max_health_value:
            return True
        if current_hp == 0 and self.was_in_level and self.last_hp is not None and self.last_hp > 0:
            return True
        return False

    def _mark_stage_clear_safe_window(self) -> None:
        self.stage_clear_cooldown_until = time.time() + 30.0
        self.stage_clear_suppress_until_positive_hp = True
        self.was_in_level = False
        self.last_hp = None
        self.ignore_next_damage = False
        self.ignore_next_death = False
        logger.info("MMX4 stage clear/loading window detected; pausing DamageLink and EnergyLink transition effects.")

    async def _add_energy_to_pool(self, ctx: "BizHawkClientContext", amount: int) -> None:
        if amount <= 0 or not self._slot_option_enabled("energy_link"):
            return

        energy_key = self._energy_key(ctx)
        await ctx.send_msgs([{
            "cmd": "Set",
            "key": energy_key,
            "default": 0,
            "want_reply": True,
            "operations": [{"operation": "add", "value": int(amount)}]
        }])
        self.current_energy_pool = self._get_energy_pool(ctx) + int(amount)
        logger.info(f"Added {amount} EnergyLink from MMX4 energy pickup. Pool is now about {self.current_energy_pool}.")
        self._update_inventory_tab_safe(ctx)

    async def _process_energy_pickups(self, ctx: "BizHawkClientContext") -> None:
        if not self._slot_option_enabled("energy_link"):
            self.processed_energy_item_count = len(ctx.items_received)
            return

        # Process each received AP item only once per client instance. Using the
        # network item's item/location/player tuple prevents old inventory from
        # being paid again every watcher tick or reconnect.
        for index, item in enumerate(getattr(ctx, "items_received", []) or []):
            key = (index, getattr(item, "item", None), getattr(item, "location", None), getattr(item, "player", None))
            if key in self.processed_energy_item_keys:
                continue
            self.processed_energy_item_keys.add(key)

            amount = ENERGY_LINK_PICKUP_VALUES.get(item.item, 0)
            if amount:
                await self._add_energy_to_pool(ctx, amount)

        self.processed_energy_item_count = len(ctx.items_received)

    async def _process_pickup_energy(self, ctx: "BizHawkClientContext", offset: int, item_data_location: int, loc_id: int) -> None:
        if not self._slot_option_enabled("energy_link"):
            return

        # The pickup log keeps appending entries. A repeated 1-up/life/weapon
        # pickup at a new offset should pay again, but re-reading the same log
        # entry should not.
        log_key = (offset, item_data_location)
        if log_key in self.processed_pickup_log_entries:
            return
        self.processed_pickup_log_entries.add(log_key)

        if loc_id in ONCE_PICKUP_ENERGY_VALUES:
            if loc_id in self.energy_once_locations_paid:
                return
            self.energy_once_locations_paid.add(loc_id)
            await self._add_energy_to_pool(ctx, ONCE_PICKUP_ENERGY_VALUES[loc_id])
            return

        amount = REPEATABLE_PICKUP_ENERGY_VALUES.get(loc_id, 0)
        if amount:
            await self._add_energy_to_pool(ctx, amount)

    def _received_item_counts(self, ctx: "BizHawkClientContext") -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in getattr(ctx, "items_received", []) or []:
            name = ITEM_ID_TO_NAME.get(item.item, f"Unknown {item.item}")
            counts[name] = counts.get(name, 0) + 1
        return counts

    def _inventory_lines(self, ctx: "BizHawkClientContext") -> list[str]:
        player_name = ctx.player_names.get(ctx.slot, "Player") if getattr(ctx, "player_names", None) and ctx.slot else "Player"
        hp = "?" if self.current_hp is None else str(self.current_hp)
        lives = "?" if self.current_lives is None else str(self.current_lives)
        max_hp = "?" if self.current_max_hp is None else str(self.current_max_hp)
        lines = [
            f"Mega Man X4 - {player_name}",
            f"HP: {hp}/{max_hp}",
            f"DeathLink Amnesty: {self._deathlink_amnesty_value()} | Lives: {lives}",
            f"EnergyLink Pool: {self.current_energy_pool}",
            f"DeathLink: {'On' if self._slot_option_enabled('death_link') else 'Off'}",
            f"DamageLink: {'On' if self._slot_option_enabled('damage_link') else 'Off'}",
            f"Auto Heal: {'On' if self._slot_option_enabled('energy_link_auto_heal') else 'Off'}",
            f"Cost Per HP: {(self.slot_data or {}).get('energy_link_cost_per_hp', 5)}",
            f"Infinite Nova: {'On' if self._slot_option_enabled('infinite_nova_strike') else 'Off'}",
            "",
            "Received Items:",
        ]

        counts = self._received_item_counts(ctx)
        if not counts:
            lines.append("  None yet")
            return lines

        # Keep the overlay readable. Important/progression items are displayed first,
        # and repeated filler shows as Name xN instead of taking many rows.
        preferred_order = [
            "Lightning Web", "Aiming Laser", "Double Cyclone", "Rising Fire", "Ground Hunter", "Soul Body",
            "Twin Slasher", "Frost Tower", "Helmet Upgrade", "Body Upgrade", "Plasma Shot Upgrade",
            "Stock Charge Upgrade", "Legs Upgrade", "Heart Tank", "Sub Tank", "Weapon Energy Tank",
            "Extra Lives Tank", "Web Spider Stage Access", "Cyber Peacock Stage Access", "Storm Owl Stage Access",
            "Magma Dragoon Stage Access", "Jet Stingray Stage Access", "Split Mushroom Stage Access",
            "Slash Beast Stage Access", "Frost Walrus Stage Access", "Small Energy", "Large Energy",
            "Small Weapon Energy", "Large Weapon Energy", "Extra Life", "Victory",
        ]
        ordered_names = [name for name in preferred_order if name in counts]
        ordered_names.extend(sorted(name for name in counts if name not in preferred_order))

        for name in ordered_names[:16]:
            count = counts[name]
            lines.append(f"  {name}" if count == 1 else f"  {name} x{count}")
        if len(ordered_names) > 16:
            lines.append(f"  ...and {len(ordered_names) - 16} more")
        return lines

    def _update_inventory_tab_safe(self, ctx: "BizHawkClientContext") -> None:
        label = getattr(self, "inventory_tab", None)
        if label is not None:
            label.text = "\n".join(self._inventory_lines(ctx))

    def attach_gui_tab(self, ctx: "BizHawkClientContext") -> None:
        """Attach a compact inventory overlay to the Kivy Window.

        The compiled Archipelago BizHawk client does not expose a normal tab
        panel to APWorld clients, so this uses a small collapsible overlay. It
        starts lower than the connection/server controls and can be collapsed by
        clicking the header so it does not sit over the main client UI.
        """
        if self.inventory_tab is not None:
            return

        from kivy.clock import Clock

        def build_overlay(_dt):
            if self.inventory_tab is not None:
                return

            from kivy.core.window import Window
            from kivy.uix.boxlayout import BoxLayout
            from kivy.uix.button import Button
            from kivy.uix.label import Label
            from kivy.uix.scrollview import ScrollView

            width = 360
            expanded_height = 330
            collapsed_height = 34
            box = BoxLayout(
                orientation="vertical",
                size_hint=(None, None),
                size=(width, expanded_height),
                x=max(0, Window.width - width - 12),
                y=max(80, Window.height - expanded_height - 90),
                padding=(6, 6),
                spacing=3,
            )
            from kivy.graphics import Color, Rectangle
            with box.canvas.before:
                Color(0.03, 0.04, 0.06, 1)
                bg_rect = Rectangle(pos=box.pos, size=box.size)
            box.bind(pos=lambda instance, value: setattr(bg_rect, "pos", value))
            box.bind(size=lambda instance, value: setattr(bg_rect, "size", value))

            def keep_inside(*_args):
                target_height = expanded_height if self.inventory_expanded else collapsed_height
                box.size = (width, target_height)
                box.x = max(0, Window.width - width - 12)
                box.y = max(80, Window.height - target_height - 90)

            header = Button(
                text="MMX4 Inventory (click to hide)",
                size_hint=(1, None),
                height=28,
            )

            scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False, do_scroll_y=True)
            label = Label(
                text="\n".join(self._inventory_lines(ctx)),
                halign="left",
                valign="top",
                size_hint=(1, None),
                markup=False,
            )
            label.bind(
                width=lambda instance, value: setattr(instance, "text_size", (value, None)),
                texture_size=lambda instance, value: setattr(instance, "height", value[1]),
            )
            scroll.add_widget(label)

            def toggle_visible(_instance):
                self.inventory_expanded = not self.inventory_expanded
                scroll.opacity = 1 if self.inventory_expanded else 0
                scroll.disabled = not self.inventory_expanded
                header.text = "MMX4 Inventory (click to hide)" if self.inventory_expanded else "MMX4 Inventory (click to show)"
                keep_inside()

            header.bind(on_release=toggle_visible)
            Window.bind(size=keep_inside)
            box.add_widget(header)
            box.add_widget(scroll)
            Window.add_widget(box)
            self.inventory_box = box
            self.inventory_tab = label
            keep_inside()
            logger.info("Added MMX4 Inventory overlay to client UI.")

        Clock.schedule_once(build_overlay, 0)

    async def _show_energy_link_ui(self, ctx: "BizHawkClientContext", current_hp: int, max_health_value: int, force: bool = False) -> None:
        if not self._slot_option_enabled("energy_link"):
            return

        pool = self._get_energy_pool(ctx)
        self.current_hp = current_hp
        self.current_max_hp = max_health_value
        self._update_inventory_tab_safe(ctx)
        now = time.time()
        cost_per_hp = max(1, int((self.slot_data or {}).get("energy_link_cost_per_hp", 5) or 5))
        message = f"EnergyLink: {pool} | HP: {current_hp}/{max_health_value} | Cost/HP: {cost_per_hp}"

        # Only print/display when the visible status actually changes.
        # This prevents the client log from being spammed every watcher tick.
        if not force and message == self.last_energy_status_text:
            return

        self.last_energy_status_text = message
        self.last_energy_pool = pool
        self.last_energy_ui_time = now
        logger.info(message)

        # Newer BizHawk helper modules expose display_message. If this Archipelago
        # version does not, the log line above still gives the client UI feedback.
        display_message = getattr(bizhawk, "display_message", None)
        if display_message is not None:
            try:
                await display_message(ctx.bizhawk_ctx, message)
            except (bizhawk.RequestFailedError, TypeError, AttributeError):
                pass

    def _register_heal_command(self, ctx: "BizHawkClientContext") -> None:
        """Register /heal with the AP client command processor when available."""
        command_processor = getattr(ctx, "command_processor", None)
        commands = getattr(command_processor, "commands", None)
        if commands is None:
            logger.warning("Could not register /heal command: command processor has no commands dictionary.")
            return

        def heal_command(raw_amount: str = "999"):
            try:
                asyncio.get_event_loop().create_task(self.command_heal(ctx, raw_amount))
            except RuntimeError:
                asyncio.run(self.command_heal(ctx, raw_amount))

        commands["heal"] = heal_command
        logger.info("Registered MMX4 /heal command. Use /heal or /heal <amount>.")

    async def command_heal(self, ctx: "BizHawkClientContext", raw_amount: str = "999") -> None:
        """Spend EnergyLink to heal current HP when auto-heal is disabled."""
        if not self._slot_option_enabled("energy_link"):
            logger.info("Cannot heal: EnergyLink is disabled for this slot.")
            return

        try:
            amount = int(str(raw_amount).strip())
        except (TypeError, ValueError):
            amount = 999
        amount = max(1, amount)

        try:
            current_hp = await self._read_current_hp(ctx)
        except bizhawk.RequestFailedError:
            logger.info("Cannot heal: BizHawk is not connected or HP could not be read.")
            return

        max_hp = 32
        for item in getattr(ctx, "items_received", []) or []:
            if getattr(item, "item", None) == 14575113:
                max_hp += 2

        if not self._is_hp_value_in_level(current_hp, max_hp):
            logger.info("Cannot heal: current HP does not look like active level gameplay.")
            return

        energy_key = self._energy_key(ctx)
        pool = self._get_energy_pool(ctx)
        cost_per_hp = max(1, int((self.slot_data or {}).get("energy_link_cost_per_hp", 5) or 5))
        missing_hp = max(0, max_hp - current_hp)
        max_affordable = pool // cost_per_hp
        heal_amount = min(amount, missing_hp, max_affordable)

        if heal_amount <= 0:
            logger.info(f"Cannot heal: HP {current_hp}/{max_hp}, EnergyLink pool {pool}, cost/HP {cost_per_hp}.")
            return

        await ctx.send_msgs([{
            "cmd": "Set",
            "key": energy_key,
            "operations": [{"operation": "add", "value": -(heal_amount * cost_per_hp)}],
            "want_reply": True
        }])

        await self._write_current_hp(ctx, current_hp + heal_amount)
        self.current_hp = current_hp + heal_amount
        self.current_max_hp = max_hp
        self.current_energy_pool = max(0, pool - heal_amount * cost_per_hp)
        self._update_inventory_tab_safe(ctx)
        logger.info(f"Healed {heal_amount} HP for {heal_amount * cost_per_hp} EnergyLink. HP is now {current_hp + heal_amount}/{max_hp}.")

    async def _notify_deathlink_enabled(self, ctx: "BizHawkClientContext") -> None:
        if not self._slot_option_enabled("death_link") or ctx.finished_game:
            return

        now = time.time()
        if now - self.last_deathlink_enabled_notice_time < 2.0:
            return

        self.last_deathlink_enabled_notice_time = now
        message = "DeathLink is now enabled"
        logger.info(message)

        display_message = getattr(bizhawk, "display_message", None)
        if display_message is not None:
            try:
                await display_message(ctx.bizhawk_ctx, message)
            except (bizhawk.RequestFailedError, TypeError, AttributeError):
                pass

    async def _handle_link_features(self, ctx: "BizHawkClientContext", max_health_value: int) -> None:
        current_hp = await self._read_current_hp(ctx)
        current_lives = await self._read_life_count(ctx)
        self.current_hp = current_hp
        self.current_lives = current_lives
        self.current_max_hp = max_health_value
        self._get_energy_pool(ctx)

        # Stage-clear / loading precautions only pause DamageLink and EnergyLink.
        # DeathLink no longer uses HP or stage-clear suppression; it only checks lives.
        in_stage_transition = False
        if self.stage_clear_suppress_until_positive_hp:
            if 0 < current_hp <= max_health_value:
                self.stage_clear_suppress_until_positive_hp = False
                self.stage_clear_cooldown_until = 0.0
            else:
                in_stage_transition = True

        if time.time() < self.stage_clear_cooldown_until and current_hp <= 0:
            in_stage_transition = True

        # First intro/tutorial level load: seed the life counter with the configured
        # DeathLink amnesty. This only runs once per client launch, and it waits
        # until HP looks like active gameplay so it does not write during menus.
        if (
            not self.initial_tutorial_amnesty_applied
            and current_hp > 0
            and current_hp <= max_health_value
        ):
            amnesty_lives = self._deathlink_amnesty_value()
            await self._write_life_count(ctx, amnesty_lives)
            current_lives = amnesty_lives
            self.current_lives = current_lives
            self.deathlink_amnesty_lives = amnesty_lives
            self.last_life_count = current_lives
            self.initial_tutorial_amnesty_applied = True
            logger.info(f"First tutorial level load detected; set MMX4 lives to DeathLink amnesty value: {amnesty_lives}.")

        await self._show_energy_link_ui(ctx, current_hp, max_health_value)

        if self.force_death_pending:
            self.force_death_pending = False
            amnesty_lives = self._deathlink_amnesty_value()
            self.pending_life_reset_value = amnesty_lives
            self.pending_life_reset_until = time.time() + 8.0
            self.deathlink_suppress_outgoing_until = time.time() + 8.0

            # Fill lives before forcing the death, then keep reapplying below for a
            # few seconds because MMX4 may decrement the counter during the death flow.
            await self._write_life_count(ctx, amnesty_lives)
            await self._force_player_death(ctx)
            current_lives = amnesty_lives
            self.current_lives = current_lives
            self.deathlink_amnesty_lives = amnesty_lives
            self.last_life_count = current_lives
            logger.info(f"Received DeathLink; forced MMX4 death and reset lives to amnesty value: {amnesty_lives}.")
            self._update_inventory_tab_safe(ctx)
            return

        # Keep the amnesty reset alive through the death/respawn transition.
        if self.pending_life_reset_until and time.time() < self.pending_life_reset_until:
            reset_value = max(1, int(self.pending_life_reset_value or self._deathlink_amnesty_value()))
            if current_lives < reset_value:
                await self._write_life_count(ctx, reset_value)
                current_lives = reset_value
                self.current_lives = current_lives
                self.last_life_count = current_lives
        elif self.pending_life_reset_until and time.time() >= self.pending_life_reset_until:
            self.pending_life_reset_until = 0.0
            self.pending_life_reset_value = 0

        if self.pending_damage > 0 and not in_stage_transition:
            damage_points = int(self.pending_damage) + int(self.pending_damage_point_remainder)
            self.pending_damage = 0
            hp_damage = damage_points // DAMAGE_LINK_POINTS_PER_HP
            self.pending_damage_point_remainder = damage_points % DAMAGE_LINK_POINTS_PER_HP
            if hp_damage > 0:
                self.ignore_next_damage = True
                current_hp = max(0, current_hp - hp_damage)
                await self._write_current_hp(ctx, current_hp)
                self.current_hp = current_hp
        elif self.pending_damage > 0 and in_stage_transition:
            # Do not let queued shared damage apply during stage loading / clear transitions.
            self.pending_damage = 0
            self.pending_damage_point_remainder = 0

        # DeathLink is based only on the MMX4 life counter. HP and stage transitions do not block it.
        # If lives hit 0, send DeathLink first, then refill lives to the current amnesty value.
        if (
            self.last_life_count is not None
            and self._slot_option_enabled("death_link")
            and not ctx.finished_game
            and self.last_life_count > 0
            and current_lives <= 255
        ):
            amnesty_lives = self._deathlink_amnesty_value()

            if time.time() >= self.deathlink_suppress_outgoing_until:
                await ctx.send_msgs([{
                    "cmd": "Bounce",
                    "tags": ["DeathLink"],
                    "data": {
                        "time": time.time(),
                        "uuid": self.damage_link_uuid,
                        "source": ctx.player_names[ctx.slot],
                        "cause": "ran out of lives in Mega Man X4"
                    }
                }])
                logger.info("Sent DeathLink for Mega Man X4 lives reaching 0.")
            else:
                logger.info("MMX4 lives reached 0 from received DeathLink; outgoing DeathLink suppressed.")

            await self._write_life_count(ctx, amnesty_lives)
            current_lives = amnesty_lives
            self.current_lives = current_lives
            self.deathlink_amnesty_lives = amnesty_lives
            self.pending_life_reset_value = amnesty_lives
            self.pending_life_reset_until = time.time() + 4.0
            logger.info(f"Reset MMX4 lives to DeathLink amnesty value: {amnesty_lives}.")

            self.last_life_count = current_lives
            self.last_hp = current_hp
            self._update_inventory_tab_safe(ctx)
            return

        if current_lives > 255:
            self.deathlink_amnesty_lives = self._deathlink_amnesty_value()

        # EnergyLink auto-heal only runs while alive and outside loading/stage-clear transitions.
        if (
            self._slot_option_enabled("energy_link")
            and self._slot_option_enabled("energy_link_auto_heal")
            and not in_stage_transition
            and current_hp > 0
            and current_lives > 0
        ):
            energy_key = self._energy_key(ctx)
            pool = self._get_energy_pool(ctx)
            cost_per_hp = max(1, int((self.slot_data or {}).get("energy_link_cost_per_hp", 5) or 5))
            missing_hp = max(0, max_health_value - current_hp)
            heal_amount = min(missing_hp, pool // cost_per_hp)
            if heal_amount > 0:
                await ctx.send_msgs([{
                    "cmd": "Set",
                    "key": energy_key,
                    "operations": [{"operation": "add", "value": -(heal_amount * cost_per_hp)}],
                    "want_reply": True
                }])
                current_hp += heal_amount
                self.current_hp = current_hp
                self.current_energy_pool = max(0, pool - heal_amount * cost_per_hp)
                await self._write_current_hp(ctx, current_hp)

        # DamageLink still uses HP loss, but it is disabled during transition screens.
        if not in_stage_transition and self.last_hp is not None:
            if self._slot_option_enabled("damage_link") and current_hp < self.last_hp:
                hp_lost = self.last_hp - current_hp
                if self.ignore_next_damage:
                    self.ignore_next_damage = False
                else:
                    damage_points = hp_lost * DAMAGE_LINK_POINTS_PER_HP
                    if current_hp > 0:
                        damage_points = min(damage_points, DAMAGE_LINK_NORMAL_CAP_POINTS)
                    await ctx.send_msgs([{
                        "cmd": "Bounce",
                        "tags": ["SharedDamage"],
                        "data": {
                            "time": time.time(),
                            "uuid": self.damage_link_uuid,
                            "source": ctx.player_names[ctx.slot],
                            "amount": damage_points,
                            "cause": "took damage in Mega Man X4"
                        }
                    }])

        if not in_stage_transition:
            self.last_hp = current_hp
        else:
            self.last_hp = None
            self.ignore_next_damage = False

        self.last_life_count = current_lives
        self._update_inventory_tab_safe(ctx)

    async def game_watcher(self, ctx: "BizHawkClientContext") -> None:
        if ctx.server is None:
            return

        if ctx.slot is None:
            return

        if not self.gui_tab_attach_tried:
            self.gui_tab_attach_tried = True
            self.attach_gui_tab(ctx)

        if self.needs_tag_update:
            self.needs_tag_update = False
            await ctx.send_msgs([{
                "cmd": "ConnectUpdate",
                "tags": list(ctx.tags)
            }])

        if self.needs_energy_setup:
            self.needs_energy_setup = False
            energy_key = self._energy_key(ctx)
            ctx.set_notify(energy_key)
            await ctx.send_msgs([{
                "cmd": "Set",
                "key": energy_key,
                "default": 0,
                "want_reply": True,
                "operations": []
            }])
        try:
            await self.location_check(ctx)
            await self._process_energy_pickups(ctx)
            #await self.received_items_check(ctx)
            # Calculate our unlocked items
            unlocked_weapons_value = 0
            unlocked_armor_value = 0
            unlocked_buster_value = 0
            # 0x20 base
            max_health_value = 32
            unlocked_tanks_value = 0
            stage_access_writes = [0, 0, 0, 0, 0, 0, 0, 0, 1]
            extra_lives_tank_count = 0
            for item in ctx.items_received:
                item_id = item.item
                # Weapons
                if item_id == 14575100:
                    unlocked_weapons_value |= 0b00000001
                if item_id == 14575101:
                    unlocked_weapons_value |= 0b00100000
                if item_id == 14575102:
                    unlocked_weapons_value |= 0b01000000
                if item_id == 14575103:
                    unlocked_weapons_value |= 0b00001000
                if item_id == 14575104:
                    unlocked_weapons_value |= 0b00010000
                if item_id == 14575105:
                    unlocked_weapons_value |= 0b00000100
                if item_id == 14575106:
                    unlocked_weapons_value |= 0b10000000
                if item_id == 14575107:
                    unlocked_weapons_value |= 0b00000010
                # Helmet
                if item_id == 14575108:
                    unlocked_armor_value |= 0b1
                # Body
                if item_id == 14575109:
                    unlocked_armor_value |= 0b10
                # Arms
                if item_id == 14575110:
                    unlocked_buster_value |= 0b10
                if item_id == 14575111:
                    unlocked_buster_value |= 0b01
                # Legs
                if item_id == 14575112:
                    unlocked_armor_value |= 0b1000
                # Heart Tanks
                if item_id == 14575113:
                    max_health_value += 2
                # Sub Tanks
                if item_id == 14575114:
                    if unlocked_tanks_value & 0b00010000 > 0:
                        unlocked_tanks_value |= 0b00100000
                    else:
                        unlocked_tanks_value |= 0b00010000
                # Weapon Energy Tank
                if item_id == 14575115:
                    unlocked_tanks_value |= 0b01000000
                # Extra Lives Tank
                if item_id == 14575116:
                    unlocked_tanks_value |= 0b10000000
                    extra_lives_tank_count += 1
                # Stage Access
                if item_id >= 14575200 and item_id <= 14575207:
                    index = item_id - 14575200
                    stage_access_writes[index] = 1
                # Victory / boss item
                # Once this has been received, stop sending outgoing DeathLinks.
                # Incoming DeathLinks are still accepted if DeathLink is enabled.
                if not ctx.finished_game and item_id == 14575400:
                    ctx.finished_game = True
                    await ctx.send_msgs([{
                        "cmd": "StatusUpdate",
                        "status": ClientStatus.CLIENT_GOAL
                    }])

            self.extra_lives_tank_count = extra_lives_tank_count

            override_weapon = False
            # Detect selected weapon to allow charging any weapon as long as you have either plasma shot or stock charge
            if (await bizhawk.read(ctx.bizhawk_ctx, [(ADDRESS_WEAPON_SELECTED, 1, self.ram)]))[0][0] > 0 and unlocked_buster_value & 0b11 > 0:
                override_weapon = True

            # Detect select press to switch between buster types
            if (await bizhawk.read(ctx.bizhawk_ctx, [(ADDRESS_SELECT_PRESSED, 1, self.ram)]))[0][0] & 1 == 1:
                self.weapon += 1
                if self.weapon == 1 and unlocked_buster_value & 0b01 == 0:
                    self.weapon += 1
                if self.weapon == 2 and unlocked_buster_value & 0b10 == 0:
                    self.weapon = 0
                if self.weapon >= 3:
                    self.weapon = 0

            if self.weapon > 0 or override_weapon:
                unlocked_armor_value |= 0b100

            # Lock here before we do our edits
            await bizhawk.lock(ctx.bizhawk_ctx)
            # Write Weapons
            await bizhawk.write(ctx.bizhawk_ctx, [(ADDRESS_WEAPONS_FLAGS, [unlocked_weapons_value], self.ram)])
            # Write Armor
            await bizhawk.write(ctx.bizhawk_ctx, [(ADDRESS_ARMOR_FLAGS, [unlocked_armor_value], self.ram)])
            # Write Buster Type
            await bizhawk.write(ctx.bizhawk_ctx, [(ADDRESS_ARMS_FLAGS, [self.weapon], self.ram)])
            # Write Max Health
            await bizhawk.write(ctx.bizhawk_ctx, [(ADDRESS_MAX_HEALTH, [max_health_value], self.ram)])
            # Write Tanks
            await bizhawk.write(ctx.bizhawk_ctx, [(ADDRESS_TANK_FLAGS, [unlocked_tanks_value], self.ram)])
            # Write Stage Access
            await bizhawk.write(ctx.bizhawk_ctx, [(ADDRESS_STAGE_ACCESS, stage_access_writes, self.ram)])
            # Optional YAML setting: keep Nova Strike / Giga Attack energy full.
            if self._slot_option_enabled("infinite_nova_strike"):
                await bizhawk.write(ctx.bizhawk_ctx, [(ADDRESS_NOVA_STRIKE_ENERGY, [0x30], self.ram)])
            await self._handle_link_features(ctx, max_health_value)
            await bizhawk.unlock(ctx.bizhawk_ctx)
            return


        except bizhawk.RequestFailedError:
            # The connector didn't respond. Exit handler and return to main loop to reconnect
            pass

    async def location_check(self, ctx: "BizHawkClientContext"):
        locs_to_send = set()
        # Read Armor Picked Up
        unlocked_armor = (await bizhawk.read(ctx.bizhawk_ctx, [(ADDRESS_ARMOR_PICKED_UP, 5, self.ram)]))[0]
        for i in range(0, 5):
            if unlocked_armor[i] > 0:
                # Head
                if i == 0:
                    locs_to_send.add(14574108)
                # Body
                elif i == 1:
                    locs_to_send.add(14574117)
                # Arms 1
                elif i == 2:
                    locs_to_send.add(14574112)
                # Arms 2
                elif i == 3:
                    locs_to_send.add(14574113)
                # Legs
                elif i == 4:
                    locs_to_send.add(14574102)

        # Read Bosses Defeated
        defeated_bosses = (await bizhawk.read(ctx.bizhawk_ctx, [(ADDRESS_BOSSES_DEFEATED, 22, self.ram)]))[0]
        if len(defeated_bosses) == 22:
            defeated_bosses_bytes = bytes(defeated_bosses)
            if self.last_bosses_defeated_bytes is not None:
                if any(defeated_bosses_bytes[i] > self.last_bosses_defeated_bytes[i] for i in range(22)):
                    self._mark_stage_clear_safe_window()
            self.last_bosses_defeated_bytes = defeated_bosses_bytes

            for i in range(0, 22):
                if defeated_bosses[i] > 0:
                    # Intro Boss
                    if i == 0:
                        locs_to_send.add(14574100)
                        locs_to_send.add(14574101)
                    # Web Spider
                    elif i == 1:
                        locs_to_send.add(14574104)
                        locs_to_send.add(14574105)
                    # Cyber Peacock
                    elif i == 2:
                        locs_to_send.add(14574109)
                        locs_to_send.add(14574110)
                    # Storm Owl
                    elif i == 3:
                        locs_to_send.add(14574114)
                        locs_to_send.add(14574115)
                    # Magma Dragoon
                    elif i == 4:
                        locs_to_send.add(14574118)
                        locs_to_send.add(14574119)
                    # Jet Stingray
                    elif i == 5:
                        locs_to_send.add(14574122)
                        locs_to_send.add(14574123)
                    # Split Mushroom
                    elif i == 6:
                        locs_to_send.add(14574125)
                        locs_to_send.add(14574126)
                    # Slash Beast
                    elif i == 7:
                        locs_to_send.add(14574128)
                        locs_to_send.add(14574129)
                    # Frost Walrus
                    elif i == 8:
                        locs_to_send.add(14574133)
                        locs_to_send.add(14574134)
                    # Memorial Hall Colonel
                    elif i == 9:
                        locs_to_send.add(14574135)
                    # Space Port Colonel
                    elif i == 10:
                        locs_to_send.add(14574136)
                    # Double / Iris
                    elif i == 11:
                        locs_to_send.add(14574137)
                    # General
                    elif i == 12:
                        locs_to_send.add(14574138)
                    # Web Spider Rematch
                    elif i == 13:
                        locs_to_send.add(14574139)
                    # Cyber Peacock Rematch
                    elif i == 14:
                        locs_to_send.add(14574140)
                    # Storm Owl Rematch
                    elif i == 15:
                        locs_to_send.add(14574141)
                    # Magma Dragoon Rematch
                    elif i == 16:
                        locs_to_send.add(14574142)
                    # Jet Stingray Rematch
                    elif i == 17:
                        locs_to_send.add(14574143)
                    # Split Mushroom Rematch
                    elif i == 18:
                        locs_to_send.add(14574144)
                    # Slash Beast Rematch
                    elif i == 19:
                        locs_to_send.add(14574145)
                    # Frost Walrus Rematch
                    elif i == 20:
                        locs_to_send.add(14574146)
                    # Sigma
                    elif i == 21:
                        locs_to_send.add(14574300)

        # Read Items Picked Up
        offset = 0
        while True:
            items_picked_up = (await bizhawk.read(ctx.bizhawk_ctx, [(ADDRESS_ITEMS_PICKED_UP + offset, 4, self.ram)]))[0]
            item_data_location = int.from_bytes(items_picked_up, "little")
            if item_data_location == 0:
                break

            loc_id_for_energy = PICKUP_POINTER_TO_LOCATION_ID.get(item_data_location)
            if loc_id_for_energy is not None:
                await self._process_pickup_energy(ctx, offset, item_data_location, loc_id_for_energy)

            # Intro Stage
            if item_data_location == 0x800F4D30:
                locs_to_send.add(14574200)
            elif item_data_location == 0x800F4D40:
                locs_to_send.add(14574201)
            elif item_data_location == 0x800F4D38:
                locs_to_send.add(14574202)
            # Web Spider
            elif item_data_location == 0x800F52B0:
                locs_to_send.add(14574203)
            elif item_data_location == 0x800F52C0:
                locs_to_send.add(14574204)
            elif item_data_location == 0x800F52B8:
                locs_to_send.add(14574103)
            # Cyber Peacock
            elif item_data_location == 0x800F7438:
                locs_to_send.add(14574106)
            elif item_data_location == 0x800F7440:
                locs_to_send.add(14574107)
            # Storm Owl
            elif item_data_location == 0x800F7700:
                locs_to_send.add(14574205)
            elif item_data_location == 0x800F7978:
                locs_to_send.add(14574206)
            elif item_data_location == 0x800F76F8:
                locs_to_send.add(14574111)
            # Magma Dragoon
            elif item_data_location == 0x800F6854:
                locs_to_send.add(14574116)
            elif item_data_location == 0x800F66B4:
                locs_to_send.add(14574207)
            elif item_data_location == 0x800F66BC:
                locs_to_send.add(14574208)
            elif item_data_location == 0x800F685C:
                locs_to_send.add(14574209)
            # Jet Stingray
            elif item_data_location == 0x800F6C40:
                locs_to_send.add(14574120)
            elif item_data_location == 0x800F6E98:
                locs_to_send.add(14574121)
            elif item_data_location == 0x800F6EA0:
                locs_to_send.add(14574210)
            # Split Mushroom
            elif item_data_location == 0x800F6320:
                locs_to_send.add(14574124)
            elif item_data_location == 0x800F6328:
                locs_to_send.add(14574211)
            elif item_data_location == 0x800F6330:
                locs_to_send.add(14574212)
            # Slash Beast
            elif item_data_location == 0x800F7D3C:
                locs_to_send.add(14574127)
            elif item_data_location == 0x800F7D44:
                locs_to_send.add(14574213)
            # Frost Walrus
            elif item_data_location == 0x800F56C0:
                locs_to_send.add(14574214)
            elif item_data_location == 0x800F56C8:
                locs_to_send.add(14574215)
            elif item_data_location == 0x800F56B8:
                locs_to_send.add(14574216)
            elif item_data_location == 0x800F56B0:
                locs_to_send.add(14574217)
            elif item_data_location == 0x800F5660:
                locs_to_send.add(14574218)
            elif item_data_location == 0x800F5680:
                locs_to_send.add(14574219)
            elif item_data_location == 0x800F5688:
                locs_to_send.add(14574220)
            elif item_data_location == 0x800F5690:
                locs_to_send.add(14574221)
            elif item_data_location == 0x800F5698:
                locs_to_send.add(14574222)
            elif item_data_location == 0x800F56A0:
                locs_to_send.add(14574223)
            elif item_data_location == 0x800F56A8:
                locs_to_send.add(14574224)
            elif item_data_location == 0x800F5668:
                locs_to_send.add(14574225)
            elif item_data_location == 0x800F5678:
                locs_to_send.add(14574226)
            elif item_data_location == 0x800F5868:
                locs_to_send.add(14574227)
            elif item_data_location == 0x800F5658:
                locs_to_send.add(14574130)
            elif item_data_location == 0x800F5670:
                locs_to_send.add(14574131)
            elif item_data_location == 0x800F5860:
                locs_to_send.add(14574132)
            # Final Weapon 1
            elif item_data_location == 0x800F86CC:
                locs_to_send.add(14574228)
            elif item_data_location == 0x800F8564:
                locs_to_send.add(14574229)
            elif item_data_location == 0x800F855C:
                locs_to_send.add(14574230)
            # Final Weapon 2
            elif item_data_location == 0x800F87E0:
                locs_to_send.add(14574231)
            elif item_data_location == 0x800F87E8:
                locs_to_send.add(14574232)
            elif item_data_location == 0x800F87F0:
                locs_to_send.add(14574233)
            elif item_data_location == 0x800F87F8:
                locs_to_send.add(14574234)
            elif item_data_location == 0x800F8910:
                locs_to_send.add(14574235)
            elif item_data_location == 0x800F8918:
                locs_to_send.add(14574236)
            elif item_data_location == 0x800F8920:
                locs_to_send.add(14574237)
            offset += 4

        defeated_locs_seen = locs_to_send.intersection(DEFEATED_LOCATION_IDS)
        if defeated_locs_seen:
            checked_locations = set(getattr(ctx, "checked_locations", set()) or set())
            newly_seen_defeated_locs = defeated_locs_seen - self.previous_defeated_locations_seen

            # The boss flag can already be set by the time the client polls.
            # Protect EnergyLink/DamageLink during weapon-get and stage-clear transitions.
            if newly_seen_defeated_locs and not newly_seen_defeated_locs.issubset(checked_locations):
                self._mark_stage_clear_safe_window()

            self.previous_defeated_locations_seen.update(defeated_locs_seen)

        if locs_to_send is not None:
            await ctx.send_msgs([{"cmd": "LocationChecks", "locations": list(locs_to_send)}])
        return

    async def received_items_check(self, ctx: "BizHawkClientContext") -> None:
        return



def launch_client(*args: str) -> None:
    from worlds._bizhawk.context import launch
    launch(*args)
