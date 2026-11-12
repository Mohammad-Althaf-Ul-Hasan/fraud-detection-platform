"""Verify torch + PyG ops we use actually work on this machine.
Fails fast before we spend 2 minutes building a graph."""
import sys


def main():
    try:
        import torch
        import torch_geometric as pyg
        from torch_geometric.nn import HeteroConv, GATConv, Linear
        from torch_geometric.data import HeteroData

        print(f"  torch: {torch.__version__}")
        print(f"  pyg:   {pyg.__version__}")

        data = HeteroData()
        # Both node types MUST share the feature dim for a given GATConv,
        # because GATConv projects both x_src and x_dst internally.
        FEAT = 4
        data["a"].x = torch.randn(10, FEAT)
        data["b"].x = torch.randn(5,  FEAT)
        ei_ab = torch.tensor([[0, 1, 2, 3, 4], [0, 1, 2, 3, 4]])
        data["a", "to", "b"].edge_index = ei_ab
        data["b", "to", "a"].edge_index = ei_ab.flip(0)

        conv = HeteroConv({
            ("a", "to", "b"): GATConv(FEAT, 8, heads=2, concat=True, add_self_loops=False),
            ("b", "to", "a"): GATConv(FEAT, 8, heads=2, concat=True, add_self_loops=False),
        }, aggr="sum")
        out = conv(data.x_dict, data.edge_index_dict)
        assert out["a"].shape == (10, 16), out["a"].shape
        assert out["b"].shape == (5, 16), out["b"].shape

        # Also verify the exact projection pattern RingGNN uses:
        # per-type Linear projecting to a shared dim, then GATConv.
        dim = 16
        proj = torch.nn.ModuleDict({
            "a": Linear(FEAT, dim),
            "b": Linear(FEAT, dim),
        })
        h = {k: torch.relu(proj[k](data.x_dict[k])) for k in data.x_dict}
        conv2 = HeteroConv({
            ("a", "to", "b"): GATConv(dim, 8, heads=2, concat=True, add_self_loops=False),
            ("b", "to", "a"): GATConv(dim, 8, heads=2, concat=True, add_self_loops=False),
        }, aggr="sum")
        out2 = conv2(h, data.edge_index_dict)
        assert out2["a"].shape == (10, 16), out2["a"].shape
        assert out2["b"].shape == (5, 16), out2["b"].shape

        print("  HeteroConv+GATConv forward pass: OK")
        print("  project-then-conv pattern (RingGNN shape): OK")
        print("VERIFIED")
        return 0
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())