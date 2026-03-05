"""Load balancer — selects best node for a request."""

from __future__ import annotations

import itertools
import logging

from .models import NodeState, BalancerStrategy
from .node_manager import NodeManager

logger = logging.getLogger("ollama-router.balancer")

_rr_counter = itertools.count()


class LoadBalancer:
    def __init__(self, node_manager: NodeManager, strategy: BalancerStrategy = BalancerStrategy.MODEL_AFFINITY):
        self.nm = node_manager
        self.strategy = strategy

    def select_node(self, model: str, strategy: BalancerStrategy | None = None) -> NodeState | None:
        """Select the best node for the given model."""
        strat = strategy or self.strategy

        # 1. Nodes with model already loaded
        loaded = self.nm.get_nodes_with_model(model, loaded_only=True)
        # 2. Nodes that have the model available (can load it)
        available = self.nm.get_nodes_with_model(model, loaded_only=False)
        # 3. All online nodes as fallback
        online = self.nm.get_online_nodes()

        if not online:
            return None

        # Filter out nodes at max concurrency
        def under_limit(nodes: list[NodeState]) -> list[NodeState]:
            return [n for n in nodes if n.in_flight < n.max_concurrent]

        candidates_loaded = under_limit(loaded)
        candidates_available = under_limit(available)
        candidates_online = under_limit(online)

        # Model affinity: strongly prefer loaded nodes
        if strat == BalancerStrategy.MODEL_AFFINITY:
            if candidates_loaded:
                return self._pick_least_loaded(candidates_loaded)
            if candidates_available:
                return self._pick_least_loaded(candidates_available)
            # Fallback: any online node (model will need to be pulled or will error)
            return self._pick_least_loaded(candidates_online) if candidates_online else None

        elif strat == BalancerStrategy.LEAST_LOADED:
            pool = candidates_loaded or candidates_available or candidates_online
            return self._pick_least_loaded(pool) if pool else None

        elif strat == BalancerStrategy.ROUND_ROBIN:
            pool = candidates_loaded or candidates_available or candidates_online
            if not pool:
                return None
            idx = next(_rr_counter) % len(pool)
            return pool[idx]

        return None

    @staticmethod
    def _pick_least_loaded(nodes: list[NodeState]) -> NodeState | None:
        if not nodes:
            return None
        return min(nodes, key=lambda n: (n.in_flight, n.avg_latency_ms))
