"""Run in a clean environment that has only the built wheel and its dependencies installed."""

import numpy as np

import warp as wp
import warp.sparse
import warp_metal

active, reason = warp_metal.status()
assert active, reason
assert "warp_metal" in wp._src.context.__file__, wp._src.context.__file__


@wp.kernel
def scale(a: wp.array[float], s: float):
    i = wp.tid()
    a[i] = a[i] * s


for device in ("metal:0", "cpu"):  # the CPU path needs the LLVM helper library of the stock package
    a = wp.array([1.0, 2.0, 3.0], dtype=float, device=device)
    wp.launch(scale, dim=3, inputs=[a, 2.0], device=device)
    np.testing.assert_allclose(a.numpy(), [2.0, 4.0, 6.0])

# host memory passed to a Metal kernel in place
host = np.arange(4096, dtype=np.float32)
wp.launch(scale, dim=host.size, inputs=[host, 0.5], device="metal:0")
wp.synchronize_device("metal:0")
np.testing.assert_allclose(host[:4], [0.0, 0.5, 1.0, 1.5])

# a module outside context/codegen that the overlay has to cover
eye = warp.sparse.bsr_identity(4, block_type=wp.float32, device="metal:0")
x = wp.ones(4, dtype=float, device="metal:0")
np.testing.assert_allclose((eye @ x).numpy(), np.ones(4))

print(f"ok: warp {wp.config.version}, warp-metal from fork {warp_metal.FORK_COMMIT[:12]}, device {wp.get_device('metal:0').name}")
