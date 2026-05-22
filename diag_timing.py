"""
diag_timing.py - test caching effect
Run twice: second run should be much faster due to STL cache.
"""
import pythoncom
pythoncom.CoInitialize()
import time

SOLUTION = r'C:\Users\gce4\Box\ES-19\CADFiles\Listed\0253.SLDPRT'
JENNY    = r'C:\Users\gce4\Box\ES-19\Spring 2026\Grading\Section 1\Quiz 3\Problem_1\Chen.Jenny-Quiz3-1.SLDPRT'

from tool_compare import compare_shapes
from tool_mass import get_mass_properties
from tool_metadata import get_file_metadata
from tool_sketch import check_sketch_status

print("=== Run 1 (cold — no cache) ===")
t = time.time()
meta   = get_file_metadata(JENNY)
mass   = get_mass_properties(JENNY)
sketch = check_sketch_status(JENNY)
shape  = compare_shapes(JENNY, SOLUTION)
print(f"  Total: {time.time()-t:.1f}s")
print(f"  Author: {meta['author']}, Mass: {mass['mass']:.3f}kg")
print(f"  Underdefined: {sketch['underdefined_sketch_names']}")
print(f"  Shape score: {shape['score']}")

print("\n=== Run 2 (warm — STL cache should help) ===")
t = time.time()
shape2 = compare_shapes(JENNY, SOLUTION)
print(f"  Shape comparison only: {time.time()-t:.1f}s")
print(f"  Score: {shape2['score']}")

print("\n=== Run 3: Second student (Rachel) — solution STL cached ===")
RACHEL = r'C:\Users\gce4\Box\ES-19\Spring 2026\Grading\Section 1\Quiz 3\Problem_1\Kondo.Rachel-Quiz3-1.SLDPRT'
t = time.time()
shape3 = compare_shapes(RACHEL, SOLUTION)
print(f"  Time: {time.time()-t:.1f}s  (solution STL reused from cache)")
print(f"  Score: {shape3['score']}")

print("\nDone.")
