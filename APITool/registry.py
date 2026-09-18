"""
The supplier/subscriber registry: one acquisition, every consumer.

A SUPPLIER is pulled. Core asks for it by name, once per refresh, and hands
the same value to every consumer after that; it returns DATA. A SUBSCRIBER
is pushed. Core hands it the refresh once every supplier it names has run;
it returns a STATUS. The two are not the same shape and cannot share one
registry: ``daemon.Publisher`` is ``Callable[[], PublishResult]`` -- nothing
in, a status out -- which is exactly a subscriber and exactly not a supplier.
Measured before it was designed (``poc_subscriber_model.py``, H2): a read
wrapped as a publisher hands its data out only through a side channel.

Why memoised, also measured (H5). A flat registry, where each consumer
fetches for itself, does not merely duplicate an expensive read. For the
fleet carrier it REFUSES one: ``capi.py`` raises inside
``FLEETCARRIER_COOLDOWN``, 900 seconds, so the second consumer gets no data
for fifteen minutes. One acquisition fanned out to every consumer is a
correctness property, not an economy.

Nothing here knows what a supplier supplies. A sheet plugin supplies the
requirements it reads from its tab; core supplies the location and the
market; a file plugin might supply the last line it wrote. The registry
knows names, order, and that each is pulled once.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

Supplier = Callable[["Refresh"], Any]


@dataclass(frozen=True)
class Subscription:
    """
    One thing a plugin publishes, and what it needs supplied first.

    ``needs`` are supplier names, pulled (and memoised) before ``publish`` is
    called. ``publish`` is handed the refresh and returns whatever status the
    caller wants to record -- a plan, a message, a count.
    """

    name: str
    needs: tuple[str, ...]
    publish: Callable[["Refresh"], Any]


class Refresh:
    """
    One refresh's context: the suppliers, what they have produced so far, and
    whatever the composition root put in reach of every consumer.

    ``env`` holds the per-refresh facts a supplier or subscriber may need and
    the registry does not interpret -- the worksheet handle, the guard core
    built, the layout, the catalog, the options a command was run with. They
    read as attributes: ``ctx.worksheet``, ``ctx.guard``.
    """

    def __init__(self, suppliers: Mapping[str, Supplier], **env: Any):
        self._suppliers: dict[str, Supplier] = dict(suppliers)
        self._cache: dict[str, Any] = {}
        # How many times each supplier actually RAN. The whole point is that
        # this never exceeds one; tests read it to prove so.
        self.calls: dict[str, int] = {}
        self.env: dict[str, Any] = dict(env)

    def __getattr__(self, name: str) -> Any:
        env = self.__dict__.get("env", {})
        if name in env:
            return env[name]
        raise AttributeError(name)

    def has(self, name: str) -> bool:
        return name in self._suppliers

    def supplied(self) -> list[str]:
        """The suppliers pulled so far, in the order they were first asked for."""
        return list(self._cache)

    def get(self, name: str) -> Any:
        """
        The named supplier's value, pulling it on the first ask and never again.

        An unknown name is an error that names the known ones: a subscription
        asking for a supplier nobody offers is a configuration mistake, and a
        silent None would let it publish garbage.
        """
        if name in self._cache:
            return self._cache[name]
        try:
            supply = self._suppliers[name]
        except KeyError:
            raise KeyError(
                f"no supplier named {name!r}; known suppliers: "
                f"{', '.join(sorted(self._suppliers)) or '(none)'}"
            ) from None
        value = supply(self)
        self._cache[name] = value
        self.calls[name] = self.calls.get(name, 0) + 1
        return value

    def run(self, subscriptions: Sequence[Subscription]) -> dict[str, Any]:
        """
        Push every subscription, in the order given, after pulling its needs.

        Returns each subscription's status by name. Order is precedence order:
        the composition root lists subscriptions in the order plugins loaded.
        """
        statuses: dict[str, Any] = {}
        for subscription in subscriptions:
            for need in subscription.needs:
                self.get(need)
            statuses[subscription.name] = subscription.publish(self)
        return statuses


def merge_suppliers(sources: Sequence[tuple[str, Mapping[str, Supplier]]]) -> dict[str, Supplier]:
    """
    One supplier table from several offerers, refusing a name offered twice.

    Two plugins both supplying ``requirements`` is the supplier-side twin of
    two plugins declaring the same cells: nobody can say which one a
    subscriber meant, so it is refused by name rather than resolved by
    accident of order.
    """
    merged: dict[str, Supplier] = {}
    offered_by: dict[str, str] = {}
    for offerer, table in sources:
        for name, supply in table.items():
            if name in merged:
                raise ValueError(
                    f"supplier {name!r} is offered by both {offered_by[name]!r} "
                    f"and {offerer!r}; a supplier has one source"
                )
            merged[name] = supply
            offered_by[name] = offerer
    return merged
